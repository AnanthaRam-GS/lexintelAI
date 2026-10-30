"""Candidate pools and a blinded labelling sheet for new retrieval-benchmark queries (step 24 labelling kit). No LLM.

Input: a queries CSV in the ``queries_template.csv`` format. For every query it retrieves with the frozen
configuration (BGE-M3 dense, BM25 k1=1.5 b=0.75, hybrid RRF K=60, BGE reranker) and pools candidates exactly as
the frozen benchmark did (``legalai-retrieval-pool-v1``, ``backend/app/services/retrieval/evaluation.py``):
each system retrieves 20, ranks 1-15 enter the pool, every system's top 5 is always kept, at most 25 candidates
per query, ordered by best rank. ``--systems`` can drop systems (the default is the four frozen ones, so the merged
benchmark judges every system's top 5).

Output (``--out-dir``):
- ``labelling_sheet.csv``: blinded (no ranks, no scores, no system names): query, chunk ID, case, court, date,
  page/paragraph, a 700-character excerpt, and empty ``human_relevance``, ``document_relevant``, ``reviewer``,
  ``notes`` columns;
- ``pool_traces.json``: each candidate's rank per system (kept away from labellers);
- ``pool_summary.json``: counts and the configuration.

Usage (from the repository root):
    .venv/bin/python data/evaluation/labelling_kit/generate_pools.py --queries my_queries.csv --out-dir /tmp/pools
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.retrieval.evaluation import (  # noqa: E402
    POOLING_VERSION,
    PoolingConfig,
    best_rank,
    deterministic_select_pool,
    judgment_row,
    trace_row,
)

QUERY_COLUMNS = ["query_id", "query_text", "mode", "intended_statutes_or_topic", "query_type", "target_family", "target_regime",
                 "author", "notes"]
REQUIRED = ["query_id", "query_text", "mode", "intended_statutes_or_topic", "author"]
SHEET_COLUMNS = ["query_id", "query_text", "blinded_order", "chunk_id", "document_id", "case_title", "court", "decision_date",
                 "page_start", "page_end", "paragraph_start", "paragraph_end", "bounded_chunk_preview", "human_relevance",
                 "document_relevant", "reviewer", "notes"]
SYSTEM_MODES = {"bm25": ("lexical", False), "dense": ("dense", False), "hybrid": ("hybrid", False), "hybrid_rerank": ("hybrid", True)}
QUERY_ID = re.compile(r"^new-q\d{3,}$")
MODES = {"public", "professional"}


def read_queries(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    errors, seen = [], set()
    for number, row in enumerate(rows, start=2):
        for column in REQUIRED:
            if not row.get(column):
                errors.append(f"line {number}: {column} is empty")
        if row.get("query_id") and not QUERY_ID.match(row["query_id"]):
            errors.append(f"line {number}: query_id must look like new-q001 (the frozen eval-q001..030 are not reused)")
        if row.get("query_id") in seen:
            errors.append(f"line {number}: duplicate query_id {row['query_id']}")
        seen.add(row.get("query_id"))
        if row.get("mode") and row["mode"] not in MODES:
            errors.append(f"line {number}: mode must be public or professional")
    if errors:
        raise SystemExit("queries CSV refused:\n" + "\n".join(errors))
    return rows


def pool_queries(queries: list[dict[str, str]], retrieve, systems: list[str], config: PoolingConfig = PoolingConfig(20, 15, 5, 25)
                 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The frozen pool-v1 selection over ``systems``; ``retrieve(query, mode, top_k, candidate_k, rerank)`` returns results."""
    judgments: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for query in queries:
        per_chunk: dict[str, dict[str, Any]] = {}
        for system in systems:
            mode, rerank = SYSTEM_MODES[system]
            for result in retrieve(query["query_text"], mode, config.candidate_depth, config.candidate_depth, rerank):
                if result.rank > config.primary_depth:
                    continue
                per_chunk.setdefault(result.chunk_id, {"result": result, "systems": {}})["systems"][system] = result
        for order, (_chunk_id, pooled) in enumerate(deterministic_select_pool(per_chunk, config), start=1):
            row = judgment_row(query["query_id"], pooled["result"], order)
            row["query_text"] = query["query_text"]
            judgments.append(row)
            trace = trace_row(query["query_id"], pooled["result"], pooled["systems"])
            trace["best_rank"] = best_rank(pooled["systems"])
            traces.append(trace)
    return judgments, traces


def write_outputs(out_dir: Path, queries: list[dict[str, str]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]],
                  systems: list[str]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "labelling_sheet.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for row in judgments:
            writer.writerow({**{column: row.get(column, "") for column in SHEET_COLUMNS},
                             "human_relevance": "", "document_relevant": "", "reviewer": "", "notes": ""})
    (out_dir / "pool_traces.json").write_text(json.dumps(traces, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {"pooling_version": POOLING_VERSION, "systems": systems, "queries": len(queries), "candidates": len(judgments),
               "per_query": {q["query_id"]: sum(1 for j in judgments if j["query_id"] == q["query_id"]) for q in queries},
               "config": {"candidate_depth": 20, "primary_depth": 15, "always_retain_top": 5, "max_pool_size": 25},
               "frozen_retrieval_config": {"dense_model": "BAAI/bge-m3", "bm25_k1": 1.5, "bm25_b": 0.75, "rrf_k": 60,
                                           "reranker_model": "BAAI/bge-reranker-v2-m3"}}
    (out_dir / "pool_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--systems", nargs="+", default=list(SYSTEM_MODES), choices=list(SYSTEM_MODES))
    parser.add_argument("--device", default="cpu", help="cpu (the frozen benchmark's device) or mps")
    args = parser.parse_args(argv)
    queries = read_queries(args.queries)

    from backend.app.api.query import retrieval_service_args
    from backend.app.core.config import Settings
    from backend.scripts.retrieve_legal_evidence import make_service

    service_args = retrieval_service_args(Settings())
    service_args.model_device, service_args.reranker_fp16 = args.device, False
    service = make_service(service_args)

    def retrieve(query: str, mode: str, top_k: int, candidate_k: int, rerank: bool):
        return service.retrieve(query, mode, top_k=top_k, candidate_k=candidate_k, rerank=rerank).results

    judgments, traces = pool_queries(queries, retrieve, args.systems)
    print(json.dumps(write_outputs(args.out_dir, queries, judgments, traces, args.systems), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
