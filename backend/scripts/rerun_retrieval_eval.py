"""Re-run the frozen 30-query retrieval benchmark on the current corpus and stores (step 24). No LLM.

Reads the frozen benchmark (``retrieval_eval_queries.json``, ``retrieval_eval_judgments.json`` with its 695 human
labels, ``retrieval_eval_pool_traces.json``) and never writes to it. For each of the four frozen systems
(BM25, dense, hybrid RRF, hybrid + BGE rerank) it retrieves with the frozen configuration and pooling
(``legalai-retrieval-pool-v1``: depth 20, per-system ranks up to 15 pooled, at most 25 candidates per query) and
writes, under ``--output-dir`` (a new versioned run folder):

- ``trace_comparison_<variant>.json``: per query and system, whether the pooled ranking equals the frozen one;
- ``metrics_<variant>.json``: P@5, pooled R@5, pooled R@20, MRR@5 and nDCG@5 (broad and strict, as in
  ``analyze_retrieval_eval.py``, whose metric functions are reused unchanged), per query and overall, beside the
  frozen numbers.

Variants:
- ``cpu_fp32``: the frozen configuration exactly (``build_retrieval_eval_set.py``: CPU, fp32 reranker).
- ``product``: the product query path (``LEGALAI_MODEL_DEVICE``, normally MPS; reranker fp16 per
  ``LEGALAI_RERANKER_FP16``).

Rankings are scored against the frozen human labels. A chunk the frozen pool never contained has no label: it is
counted as not relevant and reported (``unjudged_top5``/``unjudged_top20``). Recall is *pooled* recall: relevant
means relevant among the judged pool, not across the whole corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.analyze_retrieval_eval import (  # noqa: E402
    SYSTEMS,
    aggregate_metrics,
    compute_metrics,
    rankings_for_query,
)
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, QUERIES_PATH, TRACES_PATH  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "data/evaluation/runs/2026-10_v3_groq/retrieval"
FROZEN_RESULTS_PATH = REPO_ROOT / "data/structured/manifests/retrieval_eval_results.json"
HEADLINE = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5",
            "graded_ndcg_at_5", "strict_precision_at_5", "strict_mrr_at_5"]


class _Retriever:
    def __init__(self, service: Any) -> None:
        self.service = service

    def retrieve(self, query: str, mode: str, top_k: int, candidate_k: int, rerank: bool = False) -> list[Any]:
        return self.service.retrieve(query, mode, top_k=top_k, candidate_k=candidate_k, rerank=rerank).results


def make_service(variant: str) -> tuple[Any, dict[str, Any]]:
    from backend.app.api.query import retrieval_service_args
    from backend.app.core.config import Settings
    from backend.scripts.retrieve_legal_evidence import make_service as product_service

    args = retrieval_service_args(Settings())
    if variant == "cpu_fp32":
        args.model_device, args.reranker_fp16 = "cpu", False
    elif variant != "product":
        raise SystemExit(f"unknown variant {variant}")
    device = {"model_device": args.model_device, "reranker_fp16": bool(args.reranker_fp16)}
    return product_service(args), device


def fresh_traces(queries: list[dict[str, Any]], service: Any) -> list[dict[str, Any]]:
    from backend.app.services.retrieval.evaluation import PoolingConfig, generate_pool

    _judgments, traces = generate_pool(queries, _Retriever(service), PoolingConfig(20, 15, 5, 25))
    return traces


def compare_traces(queries: list[dict[str, Any]], frozen: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> dict[str, Any]:
    per_system: dict[str, Any] = {}
    for system in SYSTEMS:
        identical, rows = 0, {}
        for query in queries:
            old = rankings_for_query(frozen, query["query_id"], system)
            new = rankings_for_query(fresh, query["query_id"], system)
            same = old == new
            identical += same
            if not same:
                rank_field = SYSTEMS[system]["rank_field"]
                score_field = rank_field.replace("_rank", "_score")
                changed = (set(old[:5]) ^ set(new[:5])) or set(old[:5])

                def trace_detail(rows_: list[dict[str, Any]], chunk_id: str) -> dict[str, Any] | None:
                    row = next((r for r in rows_ if r["query_id"] == query["query_id"] and r["chunk_id"] == chunk_id), None)
                    return None if row is None else {k: row.get(k) for k in (rank_field, score_field, "dense_rank", "lexical_rank")}

                rows[query["query_id"]] = {
                    "frozen_top5": old[:5], "fresh_top5": new[:5],
                    "top5_set_equal": set(old[:5]) == set(new[:5]),
                    "first_difference_rank": next((i + 1 for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)) + 1),
                    "changed_chunks": {chunk: {"frozen": trace_detail(frozen, chunk), "fresh": trace_detail(fresh, chunk)} for chunk in sorted(changed)},
                }
        per_system[system] = {"identical_queries": identical, "query_count": len(queries), "differences": rows}
    return per_system


def metrics_with_unjudged(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]]) -> tuple[list, dict, dict]:
    """The frozen metric functions; chunks outside the frozen labels count as grade 0 and are reported."""
    labelled = {(row["query_id"], row["chunk_id"]) for row in judgments}
    extra, unjudged = [], defaultdict(lambda: {"top5": 0, "top20": 0})
    for query in queries:
        for system in SYSTEMS:
            ranking = rankings_for_query(traces, query["query_id"], system)
            for position, chunk_id in enumerate(ranking[:20], start=1):
                if (query["query_id"], chunk_id) not in labelled:
                    unjudged[system]["top20"] += 1
                    unjudged[system]["top5"] += position <= 5
                    labelled.add((query["query_id"], chunk_id))
                    extra.append({"query_id": query["query_id"], "chunk_id": chunk_id, "human_relevance": 0, "document_relevant": "no"})
    per_query, aggregate = compute_metrics(queries, judgments + extra, traces)
    return per_query, aggregate, {system: dict(counts) for system, counts in unjudged.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=["cpu_fp32", "product"], required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if "data/structured/manifests" in str(args.output_dir.resolve()):
        raise SystemExit("refused: the frozen manifests directory is read-only for re-runs")

    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    frozen_traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    frozen_overall = json.loads(FROZEN_RESULTS_PATH.read_text(encoding="utf-8"))["overall"]

    # Self-check: the reused metric code on the frozen traces reproduces the frozen published numbers exactly.
    _frozen_per_query, recomputed = compute_metrics(queries, judgments, frozen_traces)
    for system in SYSTEMS:
        for metric in HEADLINE:
            if recomputed["overall"][system][metric] != frozen_overall[system][metric]:
                raise SystemExit(f"metric code does not reproduce the frozen {system} {metric}")

    service, device = make_service(args.variant)
    traces = fresh_traces(queries, service)
    comparison = compare_traces(queries, frozen_traces, traces)
    per_query, aggregate, unjudged = metrics_with_unjudged(queries, judgments, traces)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    overall = {
        system: {
            "label": SYSTEMS[system]["label"],
            "rerun": {metric: aggregate["overall"][system][metric] for metric in HEADLINE},
            "frozen": {metric: frozen_overall[system][metric] for metric in HEADLINE},
            "identical_pooled_rankings": f"{comparison[system]['identical_queries']}/{comparison[system]['query_count']}",
            "unjudged_top5": unjudged.get(system, {}).get("top5", 0),
            "unjudged_top20": unjudged.get(system, {}).get("top20", 0),
        }
        for system in SYSTEMS
    }
    run = {"variant": args.variant, "device": device, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "frozen_inputs": {"queries": QUERIES_PATH.name, "judgments": JUDGMENTS_PATH.name, "traces": TRACES_PATH.name},
           "pooling": "legalai-retrieval-pool-v1 (depth 20, per-system ranks <= 15 pooled, max 25 per query)",
           "recall_caveat": "pooled recall: relevant chunks are those judged relevant in the frozen pool, not across the corpus"}
    (args.output_dir / f"metrics_{args.variant}.json").write_text(
        json.dumps({**run, "overall": overall, "per_query": per_query}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / f"trace_comparison_{args.variant}.json").write_text(
        json.dumps({**run, "systems": comparison}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({**run, "overall": overall}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
