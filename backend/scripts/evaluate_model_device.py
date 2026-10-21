"""Query-model device checks: ranking equivalence with the frozen retrieval benchmark, and latency.

``ranking`` re-runs Hybrid+Rerank for the 30 frozen benchmark queries on one
device, then compares the top-5 order and the metrics with the frozen results.
It reuses the frozen human judgments and the analyzer's metric code. Frozen
manifests are only read; output goes to ``--output-dir``, which may not be the
manifests directory.

``benchmark`` times retrieval for 10 fixed benchmark queries after warm-up:
the reranker stage and the total retrieval, with p50 and p95.

No LLM calls. The stores are opened read-only (``create_if_missing=False``).
"""

from __future__ import annotations

import argparse
from argparse import Namespace
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.app.services.query_models import active_model_device, warm_up_query_models
from backend.scripts.analyze_retrieval_eval import RESULTS_PATH, compute_metrics, rankings_for_query
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, QUERIES_PATH, TRACES_PATH
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR
from backend.scripts.retrieve_legal_evidence import DEFAULT_INDEX_NAME, make_service

MANIFESTS_DIR = QUERIES_PATH.parent.resolve()
CANDIDATE_DEPTH = 20  # frozen pooling and query-path candidate depth
PRIMARY_DEPTH = 15  # frozen traces keep ranks <= 15 (PoolingConfig.primary_depth)
METRICS = (
    "broad_precision_at_5",
    "broad_mrr_at_5",
    "graded_ndcg_at_5",
    "broad_pooled_recall_at_5",
    "broad_pooled_recall_at_20",
    "strict_precision_at_5",
    "strict_mrr_at_5",
    "strict_binary_ndcg_at_5",
)
METRIC_TOLERANCE = 1e-6
BENCHMARK_QUERY_COUNT = 10


def build_service(device: str, reranker_fp16: bool) -> Any:
    return make_service(
        Namespace(
            bm25_persist_dir=BM25_PERSIST_DIR,
            chroma_persist_dir=CHROMA_PERSIST_DIR,
            index_name=DEFAULT_INDEX_NAME,
            collection=DEFAULT_COLLECTION,
            model_device=device,
            reranker_fp16=reranker_fp16,
        )
    )


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def run_ranking(service: Any, label: str) -> dict[str, Any]:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    frozen_traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    frozen_results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    frozen_score = {(row["query_id"], row["chunk_id"]): row.get("rerank_score") for row in frozen_traces}
    pooled = {(row["query_id"], row["chunk_id"]) for row in frozen_traces}

    per_query, new_rank, unjudged = [], {}, []
    for query in queries:
        qid = query["query_id"]
        results = service.retrieve(query["query_text"], "hybrid", top_k=CANDIDATE_DEPTH, candidate_k=CANDIDATE_DEPTH, rerank=True).results
        ranking = [(result.chunk_id, float(result.rerank_score)) for result in results]
        for rank, (chunk_id, score) in enumerate(ranking, start=1):
            if rank <= PRIMARY_DEPTH:
                new_rank[(qid, chunk_id)] = (rank, score)
                if (qid, chunk_id) not in pooled:
                    unjudged.append({"query_id": qid, "chunk_id": chunk_id, "rank": rank})
        frozen_top5 = rankings_for_query(frozen_traces, qid, "hybrid_rerank")[:5]
        top5 = [chunk_id for chunk_id, _score in ranking[:5]]
        diffs = [abs(score - frozen_score[(qid, chunk_id)]) for chunk_id, score in ranking if frozen_score.get((qid, chunk_id)) is not None]
        row = {
            "query_id": qid,
            "top5": top5,
            "frozen_top5": frozen_top5,
            "top5_identical": top5 == frozen_top5,
            "top5_set_identical": set(top5) == set(frozen_top5),
            "max_abs_score_diff_vs_frozen": round(max(diffs), 6) if diffs else None,
            "top5_scores": [round(score, 6) for _chunk_id, score in ranking[:5]],
            "frozen_top5_scores": [round(frozen_score[(qid, chunk_id)], 6) for chunk_id in frozen_top5],
        }
        per_query.append(row)

    traces = []
    for row in frozen_traces:
        rank, score = new_rank.get((row["query_id"], row["chunk_id"]), (None, None))
        traces.append(row | {"rerank_rank": rank, "rerank_score": score})
    metrics = None
    if not unjudged:
        _per_query_metrics, results = compute_metrics(queries, judgments, traces)
        metrics = {key: results["overall"]["hybrid_rerank"][key] for key in METRICS}
    frozen_metrics = {key: frozen_results["overall"]["hybrid_rerank"][key] for key in METRICS}
    return {
        "label": label,
        "devices": active_model_device(),
        "query_count": len(queries),
        "top5_identical_count": sum(row["top5_identical"] for row in per_query),
        "changed_queries": [row for row in per_query if not row["top5_identical"]],
        "unjudged_chunks_in_top15": unjudged,
        "max_abs_score_diff_vs_frozen": max((row["max_abs_score_diff_vs_frozen"] or 0.0) for row in per_query),
        "metrics": metrics,
        "frozen_metrics": frozen_metrics,
        "metrics_within_tolerance": None
        if metrics is None
        else all(abs(metrics[key] - frozen_metrics[key]) <= METRIC_TOLERANCE for key in METRICS),
        "per_query": per_query,
    }


def run_benchmark(service: Any, label: str, repeats: int) -> dict[str, Any]:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))[:BENCHMARK_QUERY_COUNT]
    rerank_ms, retrieval_ms, wall_ms = [], [], []
    for _ in range(repeats):
        for query in queries:
            understanding = understand_legal_query(query["query_text"], section_ranking_mode="deterministic")
            started = perf_counter()
            retrieval = retrieve_legal_evidence(understanding, retrieval_service=service)
            wall_ms.append((perf_counter() - started) * 1000)
            stage = retrieval.timings
            rerank_ms.append(stage.reranker_ms)
            retrieval_ms.append(stage.dense_embedding_ms + stage.dense_search_ms + stage.bm25_ms + stage.rrf_ms + stage.reranker_ms)

    def summary(values: list[float]) -> dict[str, float]:
        return {"p50": round(statistics.median(values), 1), "p95": round(percentile(values, 0.95), 1), "mean": round(statistics.fmean(values), 1)}

    return {
        "label": label,
        "devices": active_model_device(),
        "query_ids": [query["query_id"] for query in queries],
        "samples": len(rerank_ms),
        "rerank_ms": summary(rerank_ms),
        "retrieval_stages_ms": summary(retrieval_ms),
        "retrieval_wall_ms": summary(wall_ms),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["ranking", "benchmark"])
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], required=True)
    parser.add_argument("--fp16", action="store_true", help="reranker in fp16 (the query embedder stays fp32)")
    parser.add_argument("--repeats", type=int, default=3, help="benchmark passes over the 10 queries")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir == MANIFESTS_DIR or MANIFESTS_DIR in output_dir.parents:
        parser.error("--output-dir must not be the frozen manifests directory")
    label = f"{args.device}-reranker-{'fp16' if args.fp16 else 'fp32'}"

    started = perf_counter()
    service = build_service(args.device, args.fp16)
    warm = warm_up_query_models(lambda: service)
    warm["wall_ms"] = round((perf_counter() - started) * 1000, 1)
    if args.mode == "ranking":
        report = run_ranking(service, label)
    else:
        report = run_benchmark(service, label, args.repeats)
    report |= {"warm_up": warm, "torch": __import__("torch").__version__, "machine": platform.machine()}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{args.mode}_{label}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    brief = {key: report[key] for key in report if key not in {"per_query", "changed_queries"}}
    brief["changed_query_ids"] = [row["query_id"] for row in report.get("changed_queries", [])]
    print(json.dumps(brief, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
