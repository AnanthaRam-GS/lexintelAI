"""Run the controlled Gemini grounded-answer smoke trial."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from time import perf_counter


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
    build_grounded_evidence_packet,
    generate_legal_answer,
)
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt
from backend.app.services.legal_citation_validation import CITED_CLAIM_TYPES
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.scripts.retrieve_legal_evidence import make_service


EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_gemini_smoke_eval.json"
PER_CASE_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_gemini_smoke_per_case.json"

SMOKE_CASES = [
    {
        "id": "SMOKE-01",
        "query": "Section 302 IPC murder bail before Sessions Court",
        "mode": AnswerMode.PUBLIC,
    },
    {
        "id": "SMOKE-02",
        "query": "After July 2024, which BNS section covers murder?",
        "mode": AnswerMode.PUBLIC,
    },
    {
        "id": "SMOKE-03",
        "query": "Can anticipatory bail under Section 438 CrPC be sought in a cheating FIR?",
        "mode": AnswerMode.PROFESSIONAL,
    },
    {
        "id": "SMOKE-04",
        "query": "Section 103 BNS and Section 302 IPC transition issue",
        "mode": AnswerMode.PROFESSIONAL,
    },
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Run retrieval and prompt construction without Gemini")
    mode.add_argument("--live", action="store_true", help="Run one Gemini generation per fixed smoke case if configured")
    parser.add_argument("--bm25-persist-dir", type=Path, default=REPO_ROOT / "bm25_store")
    parser.add_argument("--chroma-persist-dir", type=Path, default=REPO_ROOT / "chroma_store")
    parser.add_argument("--index-name", default="legalai_trusted_judgments_bm25_v1")
    parser.add_argument("--collection", default="legalai_trusted_judgments_v1")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    live = bool(args.live)
    settings = Settings()
    service = make_service(args)
    records = []
    per_case = []
    for case in SMOKE_CASES:
        records.append(run_case(case, args, service, settings, live=live))
        per_case.append(records[-1].pop("_per_case"))
    write_json(EVAL_PATH, {"schema_version": "legalai_gemini_grounded_smoke_v1", "live_requested": live, "records": records})
    write_json(PER_CASE_PATH, {"schema_version": "legalai_gemini_grounded_smoke_per_case_v1", "live_requested": live, "cases": per_case})
    print(json.dumps({"eval_path": str(EVAL_PATH), "per_case_path": str(PER_CASE_PATH), "records": records}, indent=2, ensure_ascii=False))
    return 0


def run_case(case: dict, args: argparse.Namespace, service, settings: Settings, *, live: bool) -> dict:
    total_started = perf_counter()
    qa_started = perf_counter()
    understanding = understand_legal_query(case["query"], section_ranking_mode="deterministic")
    query_understanding_ms = elapsed_ms(qa_started)
    retrieval_started = perf_counter()
    retrieval = retrieve_legal_evidence(understanding, retrieval_service=service)
    retrieval_ms = elapsed_ms(retrieval_started)
    prompt_started = perf_counter()
    packet = build_grounded_evidence_packet(understanding, retrieval)
    prompt = build_legal_answer_prompt(packet, mode=case["mode"])
    prompt_ms = elapsed_ms(prompt_started)

    result = None
    generation_status = "SKIPPED_DRY_RUN"
    errors: list[str] = []
    if live:
        if not settings.gemini_api_key or not settings.gemini_model:
            generation_status = "SKIPPED_GEMINI_CREDENTIALS_UNAVAILABLE"
            errors.append("GEMINI_CREDENTIALS_UNAVAILABLE")
        else:
            result = generate_legal_answer(
                understanding,
                retrieval,
                mode=case["mode"],
                adapter=GeminiAnswerAdapter(settings),
                prompt=prompt.prompt,
            )
            generation_status = "SUCCESS" if result.answer is not None else "FAILED"
            errors.extend(warning.code for warning in result.warnings if warning.severity == "error")

    record = base_record(case, settings, retrieval, result, generation_status, errors)
    record["query_understanding_latency_ms"] = query_understanding_ms
    record["retrieval_latency_ms"] = retrieval_ms
    record["prompt_construction_latency_ms"] = prompt_ms
    record["total_latency_ms"] = elapsed_ms(total_started)
    record["_per_case"] = {
        "id": case["id"],
        "query": case["query"],
        "mode": case["mode"].value,
        "llm_called": bool(live and settings.gemini_api_key and settings.gemini_model),
        "query_understanding": {
            "legal_regime": understanding.legal_regime.regime,
            "explicit_sections": [safe_dump(item) for item in understanding.explicit_sections],
            "predicted_sections_supplementary_only": [safe_dump(item) for item in understanding.predicted_sections],
        },
        "retrieval": {
            "evidence_ids": [item.citation_id for item in retrieval.evidence],
            "warnings": [warning.model_dump(mode="json") for warning in retrieval.warnings],
            "error": retrieval.error.model_dump(mode="json") if retrieval.error else None,
        },
        "prompt": {
            "answer_schema": prompt.answer_schema,
            "citation_policy": prompt.citation_policy,
            "character_count": prompt.character_count,
        },
        "answer": result.model_dump(mode="json") if result else None,
    }
    return record


def base_record(case: dict, settings: Settings, retrieval, result, generation_status: str, errors: list[str]) -> dict:
    evidence_ids = [item.citation_id for item in retrieval.evidence]
    validation = result.citation_validation if result else None
    issue_codes = [issue.code.value for issue in validation.issues] if validation else []
    citations = result.citations if result else []
    claims = result.claims if result else []
    claims_requiring = [claim for claim in claims if claim.claim_type.value in CITED_CLAIM_TYPES]
    claims_with_valid = {
        citation.claim_id
        for citation in citations
        if citation.evidence_id in evidence_ids and citation.claim_id in {claim.claim_id for claim in claims_requiring}
    }
    metadata = result.model_metadata if result else None
    return {
        "id": case["id"],
        "query": case["query"],
        "mode": case["mode"].value,
        "provider": "gemini",
        "configured_model": settings.gemini_model or None,
        "actual_model": metadata.actual_model_id if metadata else None,
        "retrieval_count": len(retrieval.evidence),
        "evidence_passed_count": min(5, len(retrieval.evidence)),
        "evidence_ids": evidence_ids,
        "generation_status": generation_status,
        "structured_parse_status": "SUCCESS" if result and result.answer is not None else "SKIPPED" if generation_status.startswith("SKIPPED") else "FAILED",
        "repair_attempted": bool(metadata.repair_attempted) if metadata else False,
        "repair_succeeded": metadata.repair_succeeded if metadata else None,
        "citation_count": len(citations),
        "valid_citation_count": len(citations) if validation and validation.valid else 0,
        "invalid_citation_count": len(validation.issues) if validation else 0,
        "invalid_citation_reasons": issue_codes,
        "grounding_status": result.grounding_status.value if result else None,
        "claims_requiring_citation": len(claims_requiring),
        "claims_with_valid_citation": len(claims_with_valid),
        "claims_without_citation": max(0, len(claims_requiring) - len(claims_with_valid)),
        "evidence_used": result.evidence_used if result else [],
        "evidence_unused": result.evidence_unused if result else evidence_ids,
        "warnings": [warning.code for warning in result.warnings] if result else [warning.code for warning in retrieval.warnings],
        "errors": errors,
        "generation_latency_ms": result.timings.get("generation_latency_ms") if result else None,
        "prompt_tokens": metadata.prompt_tokens if metadata else None,
        "completion_tokens": metadata.completion_tokens if metadata else None,
        "total_tokens": metadata.total_tokens if metadata else None,
        "fallback_used": bool(metadata.fallback_used) if metadata else False,
    }


def safe_dump(item) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": item}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
