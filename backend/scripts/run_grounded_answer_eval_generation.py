"""Frozen benchmark generation harness for the grounded legal answer evaluation.

Phase 0 Step 0.9C-B: generate LLM_ONLY and GROUNDED_RAG outputs for the frozen
30-query evaluation set. `--dry-run` (default) makes zero model calls and only
validates/plans the run. `--live` executes real Gemini generation and reuses
the existing frozen services (query understanding, retrieval, prompt
construction, answer generation, citation validation) without modifying them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    GeminiAnswerAdapter,
    GroundingStatus,
    LegalAnswerResult,
    LegalAnswerWarning,
    ModelGenerationMetadata,
    ModelProviderError,
    ModelUnavailableError,
    ProfessionalLegalBrief,
    PublicLegalAnswer,
    build_grounded_evidence_packet,
    generate_legal_answer,
    parse_model_payload,
)
from backend.app.services.legal_answer_prompt import (
    PROFESSIONAL_REQUIREMENTS,
    PUBLIC_REQUIREMENTS,
    SYSTEM_RULES,
    build_legal_answer_prompt,
)
from backend.app.services.legal_citation_validation import validate_claim_grounding, validate_legal_answer_citations
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.scripts.retrieve_legal_evidence import make_service


EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval.json"
OUTPUTS_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval_outputs.json"
GENERATION_SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval_generation_summary.json"
SMOKE_EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_gemini_smoke_eval.json"
REVIEW_PACKET_PATH = REPO_ROOT / "docs/LEGAL_ANSWER_EVAL_REVIEW.md"
PAIR_MAP_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval_pair_map.json"

RUN_ID = "legalai-answer-eval-generation-v1"
CONDITIONS = ("LLM_ONLY", "GROUNDED_RAG")
OUTPUTS_SCHEMA_VERSION = "legalai-grounded-answer-eval-outputs-v1"
# Client-side call pacing to respect provider per-minute capacity; distinct from
# (and does not modify) the frozen per-call retry/backoff policy in GeminiAnswerAdapter.
INTER_CALL_PACING_SECONDS = 8.0

PROVIDER_FAILURE_CODES = {
    "GEMINI_RATE_LIMIT",
    "GEMINI_TIMEOUT",
    "GEMINI_PROVIDER_ERROR",
    "GEMINI_HTTP_ERROR",
    "GEMINI_AUTH_ERROR",
    "GEMINI_EMPTY_RESPONSE",
    "GEMINI_INVALID_RESPONSE",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Validate future generation plan without model calls")
    mode.add_argument("--live", action="store_true", help="Execute live Gemini generation for all frozen examples (authorized for this benchmark only)")
    parser.add_argument("--eval-path", type=Path, default=EVAL_PATH)
    parser.add_argument("--populate-review-packet-only", action="store_true", help="Rebuild the blinded review packet from existing outputs without generating")
    parser.add_argument("--bm25-persist-dir", type=Path, default=REPO_ROOT / "bm25_store")
    parser.add_argument("--chroma-persist-dir", type=Path, default=REPO_ROOT / "chroma_store")
    parser.add_argument("--index-name", default="legalai_trusted_judgments_bm25_v1")
    parser.add_argument("--collection", default="legalai_trusted_judgments_v1")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = json.loads(args.eval_path.read_text(encoding="utf-8"))
    if args.populate_review_packet_only:
        outputs_manifest = load_or_init_outputs()
        populate_review_packet(manifest, outputs_manifest)
        print(json.dumps({"status": "REVIEW_PACKET_REBUILT"}, indent=2))
        return 0
    if not args.live:
        return run_dry_plan(manifest)
    return run_live_generation(manifest, args)


def run_dry_plan(manifest: dict[str, Any]) -> int:
    examples = manifest["examples"]
    plan = {
        "status": "DRY_RUN_ONLY",
        "live_generation_executed": False,
        "llm_calls": 0,
        "conditions": ["LLM_ONLY", "GROUNDED_RAG"],
        "example_count": len(examples),
        "planned_outputs": len(examples) * 2,
        "llm_only_contract": manifest["conditions"]["CONDITION_A"]["description"],
        "grounded_rag_contract": manifest["conditions"]["CONDITION_B"]["description"],
        "model_source": manifest["model_control"]["model_source"],
    }
    print(json.dumps(plan, indent=2))
    return 0


def run_live_generation(manifest: dict[str, Any], args: argparse.Namespace) -> int:
    verify_component_hashes_or_die(manifest)
    settings = Settings()
    verify_model_or_die(settings)
    if not settings.gemini_api_key or not settings.gemini_model:
        print(json.dumps({"status": "BLOCKED", "reason": "GEMINI_CREDENTIALS_UNAVAILABLE"}, indent=2))
        return 1

    examples = manifest["examples"]
    outputs_manifest = load_or_init_outputs()
    existing = list(outputs_manifest.get("outputs", []))
    completed_keys = completed_keys_from_outputs(existing)
    results = [record for record in existing if (record["example_id"], record["condition"]) in completed_keys]

    started_at = existing_started_at(outputs_manifest) or utc_now_iso()
    run_metadata = build_run_metadata(manifest, settings, started_at, completed_at=None)
    write_outputs(results, run_metadata, generation_status="in_progress")

    service = make_service(args)
    for example in examples:
        example_id = example["example_id"]
        query = example["query"]
        mode = AnswerMode.PUBLIC if example["mode"] == "public" else AnswerMode.PROFESSIONAL

        if (example_id, "LLM_ONLY") not in completed_keys:
            results.append(generate_llm_only_record(example_id, query, mode, settings))
            write_outputs(results, run_metadata, generation_status="in_progress")
            time.sleep(INTER_CALL_PACING_SECONDS)
        if (example_id, "GROUNDED_RAG") not in completed_keys:
            results.append(generate_grounded_rag_record(example_id, query, mode, settings, service))
            write_outputs(results, run_metadata, generation_status="in_progress")
            time.sleep(INTER_CALL_PACING_SECONDS)

    completed_at = utc_now_iso()
    run_metadata = build_run_metadata(manifest, settings, started_at, completed_at=completed_at)
    write_outputs(results, run_metadata, generation_status="completed")

    summary = build_generation_summary(results, run_metadata)
    write_json(GENERATION_SUMMARY_PATH, summary)

    outputs_manifest = load_or_init_outputs()
    populate_review_packet(manifest, outputs_manifest)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Freeze checks
# ---------------------------------------------------------------------------


def verify_component_hashes_or_die(manifest: dict[str, Any]) -> None:
    mismatches = []
    for relative_path, expected_digest in manifest["component_hashes"].items():
        actual = hashlib.sha256((REPO_ROOT / relative_path).read_bytes()).hexdigest()
        if actual != expected_digest:
            mismatches.append({"path": relative_path, "expected": expected_digest, "actual": actual})
    if mismatches:
        print(json.dumps({"status": "BLOCKED", "reason": "COMPONENT_HASH_MISMATCH", "mismatches": mismatches}, indent=2))
        raise SystemExit(1)


def verify_model_or_die(settings: Settings) -> None:
    expected_model = last_frozen_smoke_model()
    if expected_model and settings.gemini_model != expected_model:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "GEMINI_MODEL_DRIFT",
                    "expected_model": expected_model,
                    "resolved_model": settings.gemini_model,
                },
                indent=2,
            )
        )
        raise SystemExit(1)


def last_frozen_smoke_model() -> str | None:
    if not SMOKE_EVAL_PATH.exists():
        return None
    smoke = json.loads(SMOKE_EVAL_PATH.read_text(encoding="utf-8"))
    records = smoke.get("records", [])
    if not records:
        return None
    return records[0].get("configured_model")


# ---------------------------------------------------------------------------
# LLM_ONLY condition (no retrieval, no query-understanding enrichment)
# ---------------------------------------------------------------------------


def build_llm_only_prompt(query: str, mode: AnswerMode) -> str:
    requirements = PUBLIC_REQUIREMENTS if mode == AnswerMode.PUBLIC else PROFESSIONAL_REQUIREMENTS
    return "\n\n".join(
        [
            "<SYSTEM_RULES>",
            SYSTEM_RULES,
            "</SYSTEM_RULES>",
            "<ANSWER_MODE>",
            mode.value,
            "</ANSWER_MODE>",
            "<MODE_REQUIREMENTS>",
            requirements,
            "</MODE_REQUIREMENTS>",
            "<QUERY_CONTEXT>",
            json.dumps({"original_query": query}, indent=2, ensure_ascii=False),
            "</QUERY_CONTEXT>",
            "<EVIDENCE_SET>",
            "NO_RETRIEVED_EVIDENCE_AVAILABLE_IN_THIS_CONDITION",
            "</EVIDENCE_SET>",
            "<CITATION_POLICY>",
            "No retrieval evidence is provided in this condition. The citations list must be empty. "
            "Do not invent evidence IDs, case names, courts, dates, page numbers, paragraph numbers, or source URLs.",
            "</CITATION_POLICY>",
        ]
    )


def generate_llm_only_record(example_id: str, query: str, mode: AnswerMode, settings: Settings) -> dict[str, Any]:
    schema = PublicLegalAnswer if mode == AnswerMode.PUBLIC else ProfessionalLegalBrief
    adapter = GeminiAnswerAdapter(settings)
    prompt_text = build_llm_only_prompt(query, mode)

    if not settings.gemini_api_key or not settings.gemini_model:
        result = llm_only_unavailable_result(query, mode, "Gemini API key and GEMINI_MODEL must be configured before live generation.")
        return build_output_record(example_id, query, mode, "LLM_ONLY", result, retrieval=None)

    started = perf_counter()
    try:
        model_response = adapter.generate_structured_answer(prompt_text, schema=schema, mode=mode)
    except ModelUnavailableError as exc:
        result = llm_only_unavailable_result(query, mode, str(exc))
        return build_output_record(example_id, query, mode, "LLM_ONLY", result, retrieval=None)
    except ModelProviderError as exc:
        result = llm_only_provider_failure_result(query, mode, adapter.configured_model_id, exc)
        return build_output_record(example_id, query, mode, "LLM_ONLY", result, retrieval=None)

    try:
        parsed = parse_model_payload(model_response.raw_response, model_response.parsed_response, schema)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as exc:
        result = llm_only_schema_failure_result(query, mode, model_response, str(exc))
        return build_output_record(example_id, query, mode, "LLM_ONLY", result, retrieval=None)

    claims = parsed["claims"]
    citations = [citation for claim in claims for citation in claim.citations]
    result = LegalAnswerResult(
        query=query,
        mode=mode,
        answer=parsed["answer"],
        summary=parsed["summary"],
        claims=claims,
        citations=citations,
        grounding_status=GroundingStatus.UNGROUNDED,
        evidence_used=sorted({citation.evidence_id for citation in citations}),
        evidence_retrieved=[],
        evidence_unused=[],
        model_metadata=model_response.model_metadata,
        timings={"answer_generation_ms": elapsed_ms(started), **model_response.timings},
        query_understanding_version="not_applicable_llm_only",
        retrieval_version="not_applicable_llm_only",
    )
    result.citation_validation = validate_legal_answer_citations(result, SimpleNamespace(evidence=[]))
    result.grounding_status = validate_claim_grounding(result.claims, set())
    if result.citation_validation and not result.citation_validation.valid:
        result.warnings.append(
            LegalAnswerWarning(
                code="CITATION_VALIDATION_FAILED",
                message="LLM_ONLY answer referenced citations though no evidence was provided in this condition.",
            )
        )
    return build_output_record(example_id, query, mode, "LLM_ONLY", result, retrieval=None)


def llm_only_unavailable_result(query: str, mode: AnswerMode, message: str) -> LegalAnswerResult:
    metadata = ModelGenerationMetadata(provider="gemini", configured_model_id="", response_mode=mode)
    return LegalAnswerResult(
        query=query,
        mode=mode,
        answer=None,
        summary="Model generation was not executed.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[LegalAnswerWarning(code="MODEL_UNAVAILABLE", message=message, severity="error")],
        model_metadata=metadata,
        query_understanding_version="not_applicable_llm_only",
        retrieval_version="not_applicable_llm_only",
    )


def llm_only_provider_failure_result(query: str, mode: AnswerMode, configured_model_id: str, exc: ModelProviderError) -> LegalAnswerResult:
    metadata = ModelGenerationMetadata(
        provider="gemini",
        configured_model_id=configured_model_id,
        response_mode=mode,
        fallback_used=False,
        attempt_count=exc.attempt_count,
        retry_count=exc.retry_count,
        retry_reasons=exc.retry_reasons,
        final_provider_status=exc.final_provider_status or exc.code,
    )
    return LegalAnswerResult(
        query=query,
        mode=mode,
        answer=None,
        summary="Gemini generation failed before a validated structured answer was produced.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[LegalAnswerWarning(code=exc.code, message=str(exc), severity="error")],
        model_metadata=metadata,
        query_understanding_version="not_applicable_llm_only",
        retrieval_version="not_applicable_llm_only",
    )


def llm_only_schema_failure_result(query: str, mode: AnswerMode, model_response, message: str) -> LegalAnswerResult:
    metadata = model_response.model_metadata
    metadata.repair_attempted = False
    metadata.repair_reason = "No repair attempted; benchmark preserves the frozen no-repair policy."
    return LegalAnswerResult(
        query=query,
        mode=mode,
        answer=None,
        summary="Model output failed schema validation.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[LegalAnswerWarning(code="MODEL_OUTPUT_VALIDATION_FAILED", message=message, severity="error")],
        model_metadata=metadata,
        timings=model_response.timings,
        query_understanding_version="not_applicable_llm_only",
        retrieval_version="not_applicable_llm_only",
    )


# ---------------------------------------------------------------------------
# GROUNDED_RAG condition (reuses frozen orchestration unchanged)
# ---------------------------------------------------------------------------


def generate_grounded_rag_record(example_id: str, query: str, mode: AnswerMode, settings: Settings, service) -> dict[str, Any]:
    understanding = understand_legal_query(query, section_ranking_mode="deterministic")
    retrieval = retrieve_legal_evidence(understanding, retrieval_service=service)
    packet = build_grounded_evidence_packet(understanding, retrieval)
    prompt = build_legal_answer_prompt(packet, mode=mode)
    result = generate_legal_answer(
        understanding,
        retrieval,
        mode=mode,
        adapter=GeminiAnswerAdapter(settings),
        prompt=prompt.prompt,
    )
    return build_output_record(example_id, query, mode, "GROUNDED_RAG", result, retrieval=retrieval)


# ---------------------------------------------------------------------------
# Shared record building
# ---------------------------------------------------------------------------


def generation_status_from_result(result: LegalAnswerResult) -> str:
    if result.answer is not None:
        return "SUCCESS"
    codes = {warning.code for warning in result.warnings}
    if "INSUFFICIENT_RETRIEVED_AUTHORITY" in codes:
        return "INSUFFICIENT_RETRIEVED_AUTHORITY"
    if "MODEL_OUTPUT_VALIDATION_FAILED" in codes:
        return "FAILED_SCHEMA"
    if "MODEL_UNAVAILABLE" in codes:
        return "MODEL_UNAVAILABLE"
    return "FAILED_PROVIDER"


def build_output_record(
    example_id: str,
    query: str,
    mode: AnswerMode,
    condition: str,
    result: LegalAnswerResult,
    retrieval,
) -> dict[str, Any]:
    metadata = result.model_metadata
    evidence_ids = [item.citation_id for item in retrieval.evidence] if retrieval is not None else []
    validation = result.citation_validation
    generation_status = generation_status_from_result(result)
    return {
        "example_id": example_id,
        "query": query,
        "mode": mode.value,
        "condition": condition,
        "provider": metadata.provider if metadata else "gemini",
        "configured_model": metadata.configured_model_id if metadata else None,
        "actual_model": metadata.actual_model_id if metadata else None,
        "generation_status": generation_status,
        "structured_parse_status": "SUCCESS" if result.answer is not None else ("SKIPPED" if generation_status in {"INSUFFICIENT_RETRIEVED_AUTHORITY", "MODEL_UNAVAILABLE"} else "FAILED"),
        "provider_attempt_count": metadata.attempt_count if metadata else 0,
        "retry_count": metadata.retry_count if metadata else 0,
        "retry_reasons": metadata.retry_reasons if metadata else [],
        "final_provider_status": metadata.final_provider_status if metadata else None,
        "repair_attempted": bool(metadata.repair_attempted) if metadata else False,
        "repair_succeeded": metadata.repair_succeeded if metadata else None,
        "repair_reason": metadata.repair_reason if metadata else None,
        "answer_structured": result.answer.model_dump(mode="json") if result.answer is not None else None,
        "summary": result.summary,
        "citation_validation": validation.model_dump(mode="json") if validation is not None else None,
        "grounding_status": result.grounding_status.value,
        "retrieval_count": len(evidence_ids),
        "evidence_ids": evidence_ids,
        "evidence_used": result.evidence_used,
        "evidence_unused": result.evidence_unused,
        "warnings": [warning.code for warning in result.warnings],
        "errors": [warning.message for warning in result.warnings if warning.severity == "error"],
        "generation_latency_ms": result.timings.get("generation_latency_ms"),
        "answer_generation_ms": result.timings.get("answer_generation_ms"),
        "prompt_tokens": metadata.prompt_tokens if metadata else None,
        "completion_tokens": metadata.completion_tokens if metadata else None,
        "total_tokens": metadata.total_tokens if metadata else None,
        "fallback_used": bool(metadata.fallback_used) if metadata else False,
    }


# ---------------------------------------------------------------------------
# Run metadata + persistence
# ---------------------------------------------------------------------------


def build_run_metadata(manifest: dict[str, Any], settings: Settings, started_at: str, completed_at: str | None) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "eval_version": manifest["schema_version"],
        "rubric_version": manifest["rubric_version"],
        "pairing_version": manifest["pairing_version"],
        "pairing_seed": 90210,
        "provider": "gemini",
        "configured_model": settings.gemini_model,
        "ordering_strategy": "frozen manifest order; per example LLM_ONLY then GROUNDED_RAG",
        "fallback_provider_enabled": False,
        "started_at": started_at,
        "completed_at": completed_at,
        "component_hashes": manifest["component_hashes"],
    }


def completed_keys_from_outputs(outputs: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (record["example_id"], record["condition"])
        for record in outputs
        if record.get("generation_status") == "SUCCESS"
    }


def existing_started_at(outputs_manifest: dict[str, Any]) -> str | None:
    return (outputs_manifest.get("run_metadata") or {}).get("started_at")


def load_or_init_outputs() -> dict[str, Any]:
    if OUTPUTS_PATH.exists():
        return json.loads(OUTPUTS_PATH.read_text(encoding="utf-8"))
    return {
        "schema_version": OUTPUTS_SCHEMA_VERSION,
        "eval_version": "legalai-grounded-answer-eval-v1",
        "generation_status": "not_started",
        "conditions": list(CONDITIONS),
        "outputs": [],
    }


def write_outputs(results: list[dict[str, Any]], run_metadata: dict[str, Any], generation_status: str) -> None:
    payload = {
        "schema_version": OUTPUTS_SCHEMA_VERSION,
        "eval_version": "legalai-grounded-answer-eval-v1",
        "generation_status": generation_status,
        "conditions": list(CONDITIONS),
        "run_metadata": run_metadata,
        "outputs": results,
    }
    write_json(OUTPUTS_PATH, payload)


def build_generation_summary(results: list[dict[str, Any]], run_metadata: dict[str, Any]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = {condition: [] for condition in CONDITIONS}
    for record in results:
        by_condition[record["condition"]].append(record)

    def counts(records: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "attempted": len(records),
            "generated": sum(1 for record in records if record["generation_status"] == "SUCCESS"),
            "parse_success": sum(1 for record in records if record["structured_parse_status"] == "SUCCESS"),
            "failed": sum(1 for record in records if record["generation_status"] not in {"SUCCESS", "INSUFFICIENT_RETRIEVED_AUTHORITY"}),
        }

    llm_only_counts = counts(by_condition["LLM_ONLY"])
    grounded_counts = counts(by_condition["GROUNDED_RAG"])
    grounded_counts["citation_valid_outputs"] = sum(
        1 for record in by_condition["GROUNDED_RAG"] if record.get("citation_validation") and record["citation_validation"].get("valid")
    )
    grounded_counts["grounding_status_counts"] = dict(
        sorted(count_by([record for record in by_condition["GROUNDED_RAG"] if record["generation_status"] == "SUCCESS"], "grounding_status").items())
    )

    total_attempted = len(results)
    total_successful = sum(1 for record in results if record["generation_status"] == "SUCCESS")
    total_failed = total_attempted - total_successful

    return {
        "run_id": run_metadata["run_id"],
        "eval_version": run_metadata["eval_version"],
        "rubric_version": run_metadata["rubric_version"],
        "pairing_version": run_metadata["pairing_version"],
        "provider": run_metadata["provider"],
        "configured_model": run_metadata["configured_model"],
        "started_at": run_metadata["started_at"],
        "completed_at": run_metadata["completed_at"],
        "planned_outputs": 60,
        "attempted_outputs": total_attempted,
        "successful_outputs": total_successful,
        "failed_outputs": total_failed,
        "LLM_ONLY": llm_only_counts,
        "GROUNDED_RAG": grounded_counts,
        "provider_attempts": sum(record.get("provider_attempt_count") or 0 for record in results),
        "retry_count": sum(record.get("retry_count") or 0 for record in results),
        "repair_count": sum(1 for record in results if record.get("repair_attempted")),
        "fallback_used_count": sum(1 for record in results if record.get("fallback_used")),
        "token_totals": {
            "prompt_tokens": sum(record.get("prompt_tokens") or 0 for record in results),
            "completion_tokens": sum(record.get("completion_tokens") or 0 for record in results),
            "total_tokens": sum(record.get("total_tokens") or 0 for record in results),
        },
        "latency_summary_ms": {
            "sum_generation_latency": sum(record.get("generation_latency_ms") or 0 for record in results),
            "sum_answer_generation_ms": sum(record.get("answer_generation_ms") or 0 for record in results),
        },
    }


def count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(key) or "UNKNOWN"
        counts[value] = counts.get(value, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Blinded review packet
# ---------------------------------------------------------------------------


def populate_review_packet(manifest: dict[str, Any], outputs_manifest: dict[str, Any]) -> None:
    pair_map = json.loads(PAIR_MAP_PATH.read_text(encoding="utf-8"))
    pairs_by_example = {pair["example_id"]: pair for pair in pair_map["pairs"]}
    outputs_by_key = {(record["example_id"], record["condition"]): record for record in outputs_manifest.get("outputs", [])}

    lines = [
        "# Legal Answer Evaluation Review Packet",
        "",
        "Reviewer instruction: score what the answer says, not what you think the system",
        "intended. Do not reward verbosity. Do not penalize appropriate uncertainty. Do not",
        "infer missing citations. Do not correct the answer during scoring.",
        "",
        "Reviewer confidence: high / medium / low.",
        "",
        "Use scores 0-4 for positive dimensions. Use hallucination severity 0-3. Overall",
        "preference: A / B / Tie.",
        "",
        "## Review Items",
        "",
    ]

    for example in manifest["examples"]:
        example_id = example["example_id"]
        pair = pairs_by_example[example_id]
        record_a = outputs_by_key.get((example_id, pair["display_A_condition"]))
        record_b = outputs_by_key.get((example_id, pair["display_B_condition"]))

        lines.extend(
            [
                f"### {example_id}",
                f"Mode: {example['mode']}",
                f"Difficulty: {example['difficulty']}",
                f"Query: {example['query']}",
                "",
                "#### Answer A",
                "",
                render_answer_markdown(record_a),
                "",
                "#### Answer B",
                "",
                render_answer_markdown(record_b),
                "",
                "| Dimension | Answer A Score | Answer A Notes | Answer B Score | Answer B Notes |",
                "| --- | --- | --- | --- | --- |",
                "| Legal Relevance |  |  |  |  |",
                "| Legal Correctness |  |  |  |  |",
                "| Grounding / Support |  |  |  |  |",
                "| Citation Quality |  |  |  |  |",
                "| Completeness |  |  |  |  |",
                "| Uncertainty Handling |  |  |  |  |",
                "| Regime Handling |  |  |  |  |",
                "| Actionability |  |  |  |  |",
                "| Hallucination Severity |  |  |  |  |",
                "",
                "Overall preference: A / B / Tie",
                "",
                "Reviewer confidence: High / Medium / Low",
                "",
            ]
        )

    REVIEW_PACKET_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_answer_markdown(record: dict[str, Any] | None) -> str:
    if record is None:
        return "_Not yet generated._"
    if record["generation_status"] != "SUCCESS" or record["answer_structured"] is None:
        return f"_Answer unavailable ({record['generation_status']})._"
    answer = record["answer_structured"]
    parts = [f"Summary: {record.get('summary', '')}".strip()]
    for key, value in answer.items():
        if key in {"citations", "summary"}:
            continue
        if isinstance(value, list) and value:
            parts.append(f"{humanize_key(key)}:")
            parts.extend(f"- {item}" if not isinstance(item, dict) else f"- {json.dumps(item, ensure_ascii=False)}" for item in value)
        elif isinstance(value, str) and value:
            parts.append(f"{humanize_key(key)}: {value}")
    citations = answer.get("citations") or []
    if citations:
        parts.append("Citations:")
        for citation in citations:
            parts.append(f"- [{citation.get('evidence_id')}] {citation.get('supported_text', '')}")
    else:
        parts.append("Citations: none")
    return "\n".join(parts)


def humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
