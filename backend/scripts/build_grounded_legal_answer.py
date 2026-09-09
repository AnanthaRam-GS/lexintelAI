"""Build a grounded legal answer prompt without calling an LLM by default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_answer_generation import AnswerMode, build_grounded_evidence_packet, structured_dump
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.scripts.retrieve_legal_evidence import make_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Raw legal query text")
    parser.add_argument("--mode", choices=[item.value for item in AnswerMode], default=AnswerMode.PUBLIC.value)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Build prompt context and stop before model generation")
    parser.add_argument("--include-prompt", action="store_true", help="Include full prompt text in diagnostic output")
    parser.add_argument("--bm25-persist-dir", type=Path, default=REPO_ROOT / "bm25_store")
    parser.add_argument("--chroma-persist-dir", type=Path, default=REPO_ROOT / "chroma_store")
    parser.add_argument("--index-name", default="legalai_trusted_judgments_bm25_v1")
    parser.add_argument("--collection", default="legalai_trusted_judgments_v1")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    mode = AnswerMode(args.mode)
    understanding = understand_legal_query(args.query, section_ranking_mode="deterministic")
    retrieval = retrieve_legal_evidence(understanding, retrieval_service=make_service(args))
    packet = build_grounded_evidence_packet(understanding, retrieval)
    prompt = build_legal_answer_prompt(packet, mode=mode)
    payload = {
        "dry_run": True,
        "llm_called": False,
        "query_understanding": {
            "schema_version": understanding.schema_version,
            "legal_regime": understanding.legal_regime.regime,
            "explicit_sections": [structured_dump(item) for item in understanding.explicit_sections],
            "predicted_sections_supplementary_only": [structured_dump(item) for item in understanding.predicted_sections],
        },
        "retrieval": {
            "schema_version": retrieval.schema_version,
            "evidence_ids": [item.citation_id for item in retrieval.evidence],
            "evidence_metadata": [item.citation_metadata.model_dump(mode="json") for item in retrieval.evidence],
            "warnings": [item.model_dump(mode="json") for item in retrieval.warnings],
            "error": retrieval.error.model_dump(mode="json") if retrieval.error else None,
        },
        "answer_schema": prompt.answer_schema,
        "citation_policy": prompt.citation_policy,
        "prompt_character_estimate": prompt.character_count,
    }
    if args.include_prompt:
        payload["prompt"] = prompt.prompt
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
