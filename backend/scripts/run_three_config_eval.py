"""Three-configuration generation evaluation (step 24, plan Task 4.A.1): A LLM-only, B dense-only RAG, C full LegalAI.

The 30 queries are the frozen Phase-0 generation set (``legal_answer_eval.json``, read only). Every configuration
uses the product's current answer path: prompt v3 (A: its LLM-only variant, ``legal_answer_prompt_v3_llm_only``),
the configured Groq routing and fallback, and the step 23 pacing queue (never bypassed).

- **A, LLM-only:** no retrieval; the LLM-only v3 prompt; citations must stay empty.
- **B, dense-only retrieval + generation:** the product pipeline with retrieval forced to dense-only (BGE-M3, no
  BM25, no RRF, no reranker), top 5.
- **C, full LegalAI:** the product pipeline: hybrid BM25 + dense (RRF) + BGE reranker, top 5.

B and C run ``query._attempt_generation`` (the product's generation step: trusted-evidence budget, request-size
guard, prompt v3, citation validation in the frozen pipeline). Per record the script scores, from the validator's
own results:

- schema validity and truncation;
- structural grounding: valid citations / total, and whether at least one claim has a valid citation;
- unsupported citations: structured citations to IDs or cases not in the evidence (``UNKNOWN_EVIDENCE_ID``,
  ``UNSUPPORTED_CASE_REFERENCE``; in A every structured citation), plus case references written in the answer text
  that match no evidence case name (in A, every one). The text check is a heuristic (``case_references``);
  the human review sheet checks it;
- no-coverage answers (``NO_COVERAGE_STATEMENT``), for the ``negative_out_of_scope`` queries in particular;
- latency, tokens and the answering backend.

Full outputs (answers, claims, citations, evidence) go to ``--raw-dir`` outside the repository, marked UNREVIEWED.
The repository gets only per-query IDs and scores and the aggregates (``--output-dir``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval.json"
DEFAULT_OUTPUT = REPO_ROOT / "data/evaluation/runs/2026-10_v3_groq/generation"
CONFIGS = ("A_llm_only", "B_dense_rag", "C_full_legalai")
UNSUPPORTED_CODES = {"UNKNOWN_EVIDENCE_ID", "UNSUPPORTED_CASE_REFERENCE"}
PROMPT_FILES = ["backend/app/services/legal_answer_prompt_v3.py", "backend/app/services/legal_answer_prompt_v3_llm_only.py"]

_NAME = r"[A-Z][A-Za-z.&'’()-]*"
_PARTY = rf"{_NAME}(?:\s+(?:of|and|&|the|for)?\s*{_NAME}){{0,6}}"
CASE_REFERENCE = re.compile(rf"\b({_PARTY})\s+(?:v\.|vs\.?|versus)\s+({_PARTY})")
REPORTER_REFERENCE = re.compile(r"\bAIR\s+\d{4}\s+[A-Z][A-Za-z]*\s+\d+|\(\d{4}\)\s+\d+\s+SCC\s+\d+|\b\d{4}\s+SCC\s+OnLine\s+[A-Za-z]+\s+\d+")
GENERIC_PARTY_WORDS = {"state", "union", "of", "india", "the", "and", "others", "anr", "ors", "another", "govt", "government",
                       "public", "prosecutor", "nct", "delhi", "maharashtra", "uttar", "pradesh"}


# ---------------------------------------------------------------------------------------------- scoring (pure)

def case_references(text: str) -> list[str]:
    """Case names ("A v. B", "A vs B") and law-report citations (AIR, SCC) written in free text."""
    found = [f"{a} v. {b}" for a, b in CASE_REFERENCE.findall(text or "")]
    found += REPORTER_REFERENCE.findall(text or "")
    return list(dict.fromkeys(item.strip() for item in found))


def _distinctive_tokens(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-z]+", name.lower()) if len(token) > 2 and token not in GENERIC_PARTY_WORDS}


def reference_supported(reference: str, evidence_case_names: list[str]) -> bool:
    """A text reference is supported when a distinctive party word appears in an evidence case name.

    Law-report citations (AIR/SCC) never are: the evidence carries no reporter citations.
    """
    if REPORTER_REFERENCE.fullmatch(reference):
        return False
    tokens = _distinctive_tokens(reference)
    if not tokens:
        return False
    return any(tokens & _distinctive_tokens(name) for name in evidence_case_names)


def answer_text(answer: dict[str, Any] | None, summary: str | None, claims: list[dict[str, Any]]) -> str:
    """All model-written prose: answer fields, summary and claim texts (not citation metadata)."""
    parts: list[str] = [summary or ""]

    def walk(value: Any, key: str = "") -> None:
        if key in {"citations", "source_metadata", "retrieved_authorities"}:
            return
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)

    walk(answer or {})
    parts += [claim.get("text") or "" for claim in claims]
    return "\n".join(parts)


def score_record(record: dict[str, Any]) -> dict[str, Any]:
    """Per-record scores from a raw record (see ``build_record``)."""
    claims = record.get("claims") or []
    citations = [citation for claim in claims for citation in claim.get("citations") or []]
    issues = record.get("citation_issues") or []
    llm_only = record["config"] == "A_llm_only"
    rejected = {(issue.get("evidence_id"), issue.get("claim_id")) for issue in issues}
    rejected_ids = {issue.get("evidence_id") for issue in issues if issue.get("claim_id") is None}
    valid = [c for c in citations if (c.get("evidence_id"), c.get("claim_id")) not in rejected and c.get("evidence_id") not in rejected_ids]
    if llm_only:
        valid = []
    unsupported_pairs = {(i.get("evidence_id"), i.get("claim_id")) for i in issues if i.get("code") in UNSUPPORTED_CODES}
    unsupported_structured = len(citations) if llm_only else sum(
        1 for c in citations if (c.get("evidence_id"), c.get("claim_id")) in unsupported_pairs or c.get("evidence_id") in rejected_ids)
    references = case_references(answer_text(record.get("answer"), record.get("summary"), claims))
    evidence_names = [item.get("case_name") or "" for item in record.get("evidence") or []]
    unsupported_text = [ref for ref in references if llm_only or not reference_supported(ref, evidence_names)]
    valid_pairs = {(c.get("evidence_id"), c.get("claim_id")) for c in valid}
    return {
        "status": record["status"],
        "schema_valid": record["status"] == "SUCCESS",
        "truncated": record["status"] == "TRUNCATED",
        "no_coverage": bool(record.get("no_coverage")),
        "claims": len(claims),
        "citations_total": len(citations),
        "citations_valid": len(valid),
        "has_valid_claim": any((c.get("evidence_id"), claim.get("claim_id")) in valid_pairs
                               for claim in claims for c in claim.get("citations") or []),
        "unsupported_structured_citations": unsupported_structured,
        "text_case_references": len(references),
        "unsupported_text_case_references": len(unsupported_text),
        "issue_codes": sorted({issue.get("code") for issue in issues if issue.get("code")}),
    }


def aggregate(rows: list[dict[str, Any]], examples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per-configuration aggregates over scored rows ({config, example_id, scores, latency/tokens})."""
    out: dict[str, Any] = {}
    for config in CONFIGS:
        mine = [row for row in rows if row["config"] == config]
        if not mine:
            continue
        scores = [row["scores"] for row in mine]
        answered = [s for s in scores if s["schema_valid"]]
        total_citations = sum(s["citations_total"] for s in scores)
        valid_citations = sum(s["citations_valid"] for s in scores)
        unsupported = sum(s["unsupported_structured_citations"] + s["unsupported_text_case_references"] for s in scores)
        referenced = sum(s["citations_total"] + s["text_case_references"] for s in scores)
        out_of_scope = [row for row in mine if "negative_out_of_scope" in examples[row["example_id"]]["category"]]
        latencies = sorted(row["latency_s"] for row in mine if row.get("latency_s") is not None)
        out[config] = {
            "queries": len(mine),
            "statuses": dict(Counter(s["status"] for s in scores)),
            "schema_valid_rate": round(len(answered) / len(mine), 4),
            "truncation_rate": round(sum(s["truncated"] for s in scores) / len(mine), 4),
            "citations_total": total_citations,
            "citations_valid": valid_citations,
            "structural_grounding_rate": round(valid_citations / total_citations, 4) if total_citations else None,
            "answers_with_valid_claim_rate": round(sum(s["has_valid_claim"] for s in answered) / len(answered), 4) if answered else None,
            # Undefined (None) when an answer set names no authority at all: 0 of 0 is not "0% unsupported".
            "unsupported_citation_rate": round(unsupported / referenced, 4) if referenced else None,
            "unsupported_references": unsupported,
            "references_total": referenced,
            "text_case_references": sum(s["text_case_references"] for s in scores),
            "out_of_scope_queries": len(out_of_scope),
            "out_of_scope_no_coverage_rate": round(sum(row["scores"]["no_coverage"] for row in out_of_scope) / len(out_of_scope), 4) if out_of_scope else None,
            "in_scope_no_coverage_count": sum(row["scores"]["no_coverage"] for row in mine if row not in out_of_scope),
            "latency_s_median": latencies[len(latencies) // 2] if latencies else None,
            "latency_s_max": latencies[-1] if latencies else None,
            "prompt_tokens_total": sum(row.get("prompt_tokens") or 0 for row in mine),
            "completion_tokens_total": sum(row.get("completion_tokens") or 0 for row in mine),
            "reasoning_tokens_total": sum(row.get("reasoning_tokens") or 0 for row in mine),
            "fallback_used": sum(1 for row in mine if row.get("fallback_used")),
        }
    return out


# ---------------------------------------------------------------------------------------------- running

class DenseOnlyService:
    """Configuration B: the product retrieval service with retrieval forced to dense-only and no reranker."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def retrieve(self, query: str, mode: str = "hybrid", *, top_k: int = 5, candidate_k: int | None = None,
                 filters: dict[str, Any] | None = None, rerank: bool = False) -> Any:
        return self.inner.retrieve(query, "dense", top_k=top_k, candidate_k=candidate_k, filters=filters, rerank=False)


def build_record(config: str, example: dict[str, Any], result: Any, *, evidence: list[Any], status: str, latency_s: float,
                 error_code: str | None = None) -> dict[str, Any]:
    from backend.app.services.legal_answer_prompt_v2 import is_no_coverage_answer

    metadata = result.model_metadata if result is not None else None
    validation = result.citation_validation if result is not None else None
    timings = result.timings if result is not None else {}
    return {
        "review_status": "UNREVIEWED",
        "config": config,
        "example_id": example["example_id"],
        "query": example["query"],
        "mode": example["mode"],
        "category": example["category"],
        "status": status,
        "error_code": error_code,
        "answer": result.answer.model_dump(mode="json") if result is not None and result.answer is not None else None,
        "summary": result.summary if result is not None else None,
        "claims": [claim.model_dump(mode="json") for claim in result.claims] if result is not None else [],
        "citation_issues": [issue.model_dump(mode="json") for issue in validation.issues] if validation is not None else [],
        "grounding_status": result.grounding_status.value if result is not None else None,
        "no_coverage": bool(result is not None and is_no_coverage_answer(result.summary)),
        "warnings": [warning.code for warning in result.warnings] if result is not None else [],
        "evidence": [
            {"evidence_id": item.citation_id, "chunk_id": item.chunk_id, "document_id": item.document_id,
             "case_name": item.case_name, "rank": item.rank, "text_excerpt": (item.text or "")[:600]}
            for item in evidence
        ],
        "backend": {
            "provider": metadata.provider if metadata else None,
            "model": (metadata.actual_model_id or metadata.configured_model_id) if metadata else None,
            "fallback_used": bool(metadata.fallback_used) if metadata else False,
            "fallback_reason": metadata.fallback_reason if metadata else None,
            "prompt_version": metadata.prompt_version if metadata else None,
            "finish_reason": metadata.finish_reason if metadata else None,
        },
        "prompt_tokens": metadata.prompt_tokens if metadata else None,
        "completion_tokens": metadata.completion_tokens if metadata else None,
        "reasoning_tokens": metadata.reasoning_tokens if metadata else None,
        "queue_wait_ms": timings.get("queue_wait_ms"),
        "latency_s": round(latency_s, 2),
    }


def status_of(result: Any) -> str:
    if result.answer is not None:
        return "SUCCESS"
    codes = {warning.code for warning in result.warnings}
    if any(code.endswith("_OUTPUT_TRUNCATED") for code in codes):
        return "TRUNCATED"
    if "MODEL_OUTPUT_VALIDATION_FAILED" in codes:
        return "SCHEMA_FAILED"
    if "INSUFFICIENT_RETRIEVED_AUTHORITY" in codes:
        return "INSUFFICIENT_RETRIEVAL"
    return "PROVIDER_ERROR"


def run_llm_only(example: dict[str, Any], adapter: Any) -> dict[str, Any]:
    from backend.app.services.legal_answer_generation import (
        AnswerMode, GroundingStatus, LegalAnswerResult, LegalAnswerWarning, ModelProviderError, ModelUnavailableError,
        ProfessionalLegalBrief, PublicLegalAnswer, parse_model_payload,
    )
    from backend.app.services.legal_answer_prompt_v3_llm_only import PROMPT_V3_LLM_ONLY, build_legal_answer_prompt_v3_llm_only
    from backend.app.services.legal_citation_validation import validate_legal_answer_citations
    from backend.app.services.llm_provider_chain import GenerationQueueTimeout

    mode = AnswerMode(example["mode"])
    schema = PublicLegalAnswer if mode == AnswerMode.PUBLIC else ProfessionalLegalBrief
    started = time.monotonic()
    try:
        response = adapter.generate_structured_answer(build_legal_answer_prompt_v3_llm_only(example["query"], mode=mode),
                                                      schema=schema, mode=mode)
    except GenerationQueueTimeout:
        return build_record("A_llm_only", example, None, evidence=[], status="BUSY", latency_s=time.monotonic() - started, error_code="MODEL_BUSY")
    except (ModelProviderError, ModelUnavailableError) as exc:
        code = getattr(exc, "code", "MODEL_UNAVAILABLE")
        status = "TRUNCATED" if code.endswith("_OUTPUT_TRUNCATED") else "PROVIDER_ERROR"
        return build_record("A_llm_only", example, None, evidence=[], status=status, latency_s=time.monotonic() - started, error_code=code)
    try:
        parsed = parse_model_payload(response.raw_response, response.parsed_response, schema)
    except Exception:  # noqa: BLE001 - any schema failure is the measured outcome
        return build_record("A_llm_only", example, None, evidence=[], status="SCHEMA_FAILED", latency_s=time.monotonic() - started,
                            error_code="MODEL_OUTPUT_VALIDATION_FAILED")
    claims = parsed["claims"]
    citations = [citation for claim in claims for citation in claim.citations]
    metadata = response.model_metadata.model_copy(update={"prompt_version": PROMPT_V3_LLM_ONLY})
    result = LegalAnswerResult(
        query=example["query"], mode=mode, answer=parsed["answer"], summary=parsed["summary"], claims=claims, citations=citations,
        grounding_status=GroundingStatus.UNGROUNDED, evidence_used=sorted({c.evidence_id for c in citations}), evidence_retrieved=[],
        evidence_unused=[], model_metadata=metadata, timings=response.timings, query_understanding_version="not_applicable_llm_only",
        retrieval_version="not_applicable_llm_only",
    )
    result.citation_validation = validate_legal_answer_citations(result, SimpleNamespace(evidence=[]))
    if citations:
        result.warnings.append(LegalAnswerWarning(code="CITATION_VALIDATION_FAILED", message="LLM-only answer cited evidence."))
    return build_record("A_llm_only", example, result, evidence=[], status="SUCCESS", latency_s=time.monotonic() - started)


def run_pipeline(config: str, example: dict[str, Any], adapter: Any, service: Any, settings: Any) -> dict[str, Any]:
    from backend.app.api import query as query_api
    from backend.app.services.legal_answer_generation import AnswerMode
    from backend.app.services.legal_query_understanding import understand_legal_query
    from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
    from backend.app.services.product_context_budget import resolve_product_context_budget
    from backend.app.services.token_budget import estimate_tokens

    mode = AnswerMode(example["mode"])
    started = time.monotonic()
    understanding = understand_legal_query(example["query"], section_ranking_mode="deterministic")
    retrieval = retrieve_legal_evidence(understanding, retrieval_service=service)
    try:
        result, _tier, bounded = query_api._attempt_generation(
            query=example["query"], query_tokens=estimate_tokens(example["query"]), understanding=understanding, retrieval=retrieval,
            mode=mode, adapter=adapter, product_budget=resolve_product_context_budget(settings), tier=query_api.ContextTier.NORMAL,
            private_context_builder=None, timings={}, size_guard=query_api.request_size_guard(settings, mode),
            generation_limit=query_api.generation_limit(settings), prompt=query_api.prompt_builder(settings),
        )
    except query_api.QueryExecutionError as exc:
        status = "BUSY" if exc.code == "MODEL_BUSY" else "REQUEST_REFUSED"
        return build_record(config, example, None, evidence=list(retrieval.evidence), status=status,
                            latency_s=time.monotonic() - started, error_code=exc.code)
    return build_record(config, example, result, evidence=list(bounded.evidence), status=status_of(result),
                        latency_s=time.monotonic() - started)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, required=True, help="full outputs (UNREVIEWED), outside the repository")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=CONFIGS)
    parser.add_argument("--limit", type=int, default=None, help="first N queries only")
    parser.add_argument("--score-only", action="store_true", help="re-score existing raw records, no generation")
    args = parser.parse_args(argv)
    raw_dir = args.raw_dir.resolve()
    if raw_dir == REPO_ROOT or REPO_ROOT in raw_dir.parents:
        raise SystemExit("refused: --raw-dir must be outside the repository (it holds answer text)")
    if "data/structured/manifests" in str(args.output_dir.resolve()):
        raise SystemExit("refused: the frozen manifests directory is read-only")

    examples = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["examples"][: args.limit]
    by_id = {example["example_id"]: example for example in examples}
    raw_dir.mkdir(parents=True, exist_ok=True)

    if not args.score_only:
        from backend.app.api.query import ANSWER_ADAPTER_FACTORIES, retrieval_service_args
        from backend.app.core.config import Settings
        from backend.app.services.llm_provider_chain import build_answer_adapter
        from backend.scripts.retrieve_legal_evidence import make_service

        settings = Settings()
        service = make_service(retrieval_service_args(settings))
        dense_service = DenseOnlyService(service)
        # Interleaved per query (A, B, C), so provider conditions over time affect the three configurations alike.
        for example in examples:
            for config in args.configs:
                path = raw_dir / config / f"{example['example_id']}.json"
                if path.exists():
                    continue
                adapter = build_answer_adapter(settings, ANSWER_ADAPTER_FACTORIES)
                if config == "A_llm_only":
                    record = run_llm_only(example, adapter)
                else:
                    record = run_pipeline(config, example, adapter, dense_service if config == "B_dense_rag" else service, settings)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
                print(json.dumps({"config": config, "example_id": example["example_id"], "status": record["status"],
                                  "model": record["backend"]["model"], "latency_s": record["latency_s"]}), flush=True)

    rows = []
    for config in args.configs:
        for path in sorted((raw_dir / config).glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["example_id"] not in by_id:
                continue
            rows.append({
                "config": config, "example_id": record["example_id"], "mode": record["mode"], "scores": score_record(record),
                "model": record["backend"]["model"], "fallback_used": record["backend"]["fallback_used"],
                "latency_s": record["latency_s"], "queue_wait_ms": record.get("queue_wait_ms"), "prompt_tokens": record.get("prompt_tokens"),
                "completion_tokens": record.get("completion_tokens"), "reasoning_tokens": record.get("reasoning_tokens"),
                "evidence_chunk_ids": [item["chunk_id"] for item in record.get("evidence") or []],
            })
    from backend.app.core.config import Settings

    settings = Settings()
    provenance = {
        "run": "2026-10_v3_groq", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queries": f"{EVAL_PATH.name} ({len(examples)} examples, read only)",
        "provider": "groq", "models": {"professional": settings.groq_model, "public": settings.groq_public_model or settings.groq_model,
                                       "fallback_provider": settings.legalai_llm_fallback_provider,
                                       "fallback_models": {"professional": settings.groq_backup_model, "public": settings.groq_backup_public_model}},
        "prompts": {"B_C": "legal_answer_prompt_v3", "A": "legal_answer_prompt_v3_llm_only",
                    "sha256": {path: sha256(REPO_ROOT / path) for path in PROMPT_FILES}},
        "pacing": {"queue_max_wait_s": settings.legalai_llm_queue_max_wait_seconds,
                   "professional_primary_max_wait_s": settings.legalai_professional_primary_max_wait_seconds},
        "unsupported_citation_definition": "structured citations to IDs or cases not in the evidence (A: all) plus free-text case references matching no evidence case name (A: all); text matching is heuristic",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "per_query_scores.json").write_text(json.dumps({**provenance, "rows": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    answered_by_all = {example_id for example_id in by_id
                       if all(any(r["config"] == c and r["example_id"] == example_id and r["scores"]["schema_valid"] for r in rows)
                              for c in args.configs)}
    summary = {
        **provenance,
        "configurations": aggregate(rows, by_id),
        "by_mode": {mode: aggregate([r for r in rows if r["mode"] == mode], by_id) for mode in ("public", "professional")},
        # Paired comparison: only the queries every configuration answered (schema-valid), so all see the same questions.
        "paired_answered_by_all": {"example_ids": sorted(answered_by_all),
                                   "configurations": aggregate([r for r in rows if r["example_id"] in answered_by_all], by_id)},
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary["configurations"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
