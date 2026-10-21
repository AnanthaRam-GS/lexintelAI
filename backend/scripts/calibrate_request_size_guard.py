"""Calibrate the Groq request-size guard against provider-reported prompt tokens (offline, no LLM calls).

For every saved live run (``--runs-dir``, outside the repository) whose record
has Groq's reported ``prompt_tokens``, this rebuilds the prompt that was sent:
- the same query, re-retrieved and re-understood;
- the evidence restricted to the captured chunk IDs, which are checked to match;
- prompt v1 or v2, as recorded;
- the captured private (P#) excerpt, for PDF runs.

It then compares the guard's estimate with the real count, picks the smallest
factor that never underestimates a recorded run (plus ``--margin``), and
replays the guard for the step 11d public runs (P1, P4) to count the evidence
items each factor keeps. Output: JSON with chunk IDs and token counts only.
"""

from __future__ import annotations

import argparse
from argparse import Namespace
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.api.query import RequestSizeGuard, prompt_with_private_pdf_context, retrieval_service_args
from backend.app.core.config import Settings
from backend.app.services.case_names import normalized_for_generation
from backend.app.services.groq_answer_adapter import groq_payload_schema
from backend.app.services.legal_answer_generation import AnswerMode, ProfessionalLegalBrief, PublicLegalAnswer, build_grounded_evidence_packet
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt
from backend.app.services.legal_answer_prompt_v2 import build_legal_answer_prompt_v2
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.app.services.private_pdf_rag import PrivateChunk, PrivateEvidenceItem, render_private_evidence_block
from backend.app.services.product_context_budget import bound_trusted_evidence, resolve_product_context_budget
from backend.app.services.token_budget import estimate_tokens
from backend.scripts.retrieve_legal_evidence import make_service

CEILING_TOKENS = 8000
MAX_OUTPUT_TOKENS = 2048
CURRENT_FACTOR = 1.7


def schema_tokens(mode: AnswerMode) -> int:
    return estimate_tokens(json.dumps(groq_payload_schema(PublicLegalAnswer if mode == AnswerMode.PUBLIC else ProfessionalLegalBrief)))


def private_context(record: dict[str, Any]) -> str | None:
    chunks = record["capture"].get("private_chunks") or []
    if not chunks:
        return None
    filename = str(record["request"].get("file", "document.pdf")).split(" ")[0]
    items = [
        PrivateEvidenceItem(
            chunk=PrivateChunk(
                private_chunk_id=chunk["id"], chunk_index=index, text=chunk["text"], token_count=estimate_tokens(chunk["text"]),
                page_start=chunk["pages"][0], page_end=chunk["pages"][-1],
            ),
            score=0.0,
        )
        for index, chunk in enumerate(chunks)
    ]
    return render_private_evidence_block(items, filename=filename)


def build_prompt(retrieval: Any, understanding: Any, mode: AnswerMode, version: str, private: str | None) -> str:
    if version.endswith("v2"):
        prompt = build_legal_answer_prompt_v2(build_grounded_evidence_packet(understanding, normalized_for_generation(retrieval)), mode=mode).prompt
    else:
        prompt = build_legal_answer_prompt(build_grounded_evidence_packet(understanding, retrieval), mode=mode).prompt
    return prompt_with_private_pdf_context(prompt, private)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True, help="directory of live-run output folders")
    parser.add_argument("--margin", type=float, default=0.05, help="relative safety margin over the worst recorded ratio")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    settings = Settings()
    service = make_service(retrieval_service_args(settings))
    product = resolve_product_context_budget(settings)
    rows, replays = [], {}
    for path in sorted(args.runs_dir.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        meta = (record.get("capture") or {}).get("model_metadata") or {}
        if meta.get("provider") != "groq" or not meta.get("prompt_tokens"):
            continue
        capture = record["capture"]
        mode = AnswerMode.PUBLIC if "public" in record["kind"] else AnswerMode.PROFESSIONAL
        version = meta.get("prompt_version") or "legal_answer_prompt_v1"
        query = capture["retrieval_query"]
        understanding = understand_legal_query(query, section_ranking_mode="deterministic")
        retrieval = retrieve_legal_evidence(understanding, retrieval_service=service)
        bounded = bound_trusted_evidence(retrieval, budget_tokens=product.trusted_evidence_budget(query_tokens=estimate_tokens(query)))
        captured = [(item["citation_id"], item["chunk_id"]) for item in capture["evidence"]]
        by_chunk = {item.chunk_id: item for item in bounded.evidence}
        kept = [by_chunk[chunk_id] for _citation, chunk_id in captured if chunk_id in by_chunk]
        rebuilt = [(item.citation_id, item.chunk_id) for item in kept]
        sent = bounded.model_copy(update={"evidence": kept})
        private = private_context(record)
        prompt = build_prompt(sent, understanding, mode, version, private)
        estimate = estimate_tokens(prompt) + schema_tokens(mode)
        actual = int(meta["prompt_tokens"])
        run = f"{path.parent.name}/{path.stem}"
        rows.append({
            "run": run, "mode": mode.value, "prompt_version": version.replace("legal_answer_prompt_", ""), "evidence_items": len(kept),
            "evidence_matches_capture": rebuilt == captured, "estimate_prompt_plus_schema": estimate, "actual_prompt_tokens": actual,
            "ratio": round(actual / estimate, 4), "predicted_at_1_7": round(estimate * CURRENT_FACTOR),
        })
        if path.parent.name == "20261020T162033Z":  # step 11d P1/P4: replay the guard on the full bounded evidence
            replays[run] = (bounded, understanding, mode, version, private)

    worst = max(row["ratio"] for row in rows)
    factor = math.ceil(worst * (1 + args.margin) * 100) / 100
    for row in rows:
        row["predicted_new"] = round(row["estimate_prompt_plus_schema"] * factor)
        row["new_minus_actual"] = row["predicted_new"] - row["actual_prompt_tokens"]
        row["old_minus_actual"] = row["predicted_at_1_7"] - row["actual_prompt_tokens"]

    def items_kept(bounded: Any, understanding: Any, mode: AnswerMode, version: str, private: str | None, guard_factor: float) -> int:
        guard = RequestSizeGuard(ceiling_tokens=CEILING_TOKENS, max_output_tokens=MAX_OUTPUT_TOKENS, estimate_factor=guard_factor)
        evidence = sorted(bounded.evidence, key=lambda item: item.rank)
        while len(evidence) > 1 and not guard.fits(build_prompt(bounded.model_copy(update={"evidence": evidence}), understanding, mode, version, private), mode):
            evidence = evidence[:-1]
        return len(evidence)

    replay = {
        run: {"bounded_items": len(values[0].evidence), "kept_at_1_7": items_kept(*values, CURRENT_FACTOR), "kept_at_new": items_kept(*values, factor)}
        for run, values in replays.items()
    }
    report = {"worst_ratio": worst, "margin": args.margin, "new_factor": factor, "current_factor": CURRENT_FACTOR, "runs": rows, "replay_11d": replay,
              "ceiling_tokens": CEILING_TOKENS, "max_output_tokens": MAX_OUTPUT_TOKENS}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
