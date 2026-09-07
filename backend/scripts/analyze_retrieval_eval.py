"""Analyze frozen retrieval evaluation traces against human qrels."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, QUERIES_PATH, SUMMARY_PATH, TRACES_PATH
from backend.scripts.materialize_retrieval_eval_labels import HUMAN_LABEL_SUMMARY_PATH

RESULTS_PATH = SUMMARY_PATH.parent / "retrieval_eval_results.json"
PER_QUERY_PATH = SUMMARY_PATH.parent / "retrieval_eval_per_query_metrics.json"
COVERAGE_PATH = SUMMARY_PATH.parent / "retrieval_eval_judged_coverage.json"
BOOTSTRAP_PATH = SUMMARY_PATH.parent / "retrieval_eval_bootstrap.json"
RESULTS_DOC = SUMMARY_PATH.parents[3] / "docs/RETRIEVAL_EVALUATION_RESULTS.md"

SYSTEMS = {
    "bm25": {"label": "BM25", "rank_field": "lexical_rank"},
    "dense": {"label": "Dense", "rank_field": "dense_rank"},
    "hybrid": {"label": "Hybrid", "rank_field": "hybrid_rank"},
    "hybrid_rerank": {"label": "Hybrid+Rerank", "rank_field": "rerank_rank"},
}
EXPECTED_RELEVANCE = {"2": 251, "1": 222, "0": 219, "uncertain": 3}
EXPECTED_DOCUMENT = {"yes": 466, "no": 223, "uncertain": 6}


def is_relevant(grade: int | str, policy: str) -> bool | None:
    if grade == "uncertain":
        return None
    if policy == "broad":
        return grade in {1, 2}
    if policy == "strict":
        return grade == 2
    raise ValueError(f"unknown policy: {policy}")


def precision_at_k(ranking: list[str], labels: dict[str, int | str], k: int, policy: str) -> float:
    top = ranking[:k]
    if len(top) != k:
        raise ValueError("precision@k requires complete judged top-k")
    return sum(1 for chunk_id in top if is_relevant(labels[chunk_id], policy) is True) / k


def pooled_recall_at_k(ranking: list[str], labels: dict[str, int | str], k: int, policy: str) -> float | None:
    relevant = {chunk_id for chunk_id, grade in labels.items() if is_relevant(grade, policy) is True}
    if not relevant:
        return None
    return len(set(ranking[:k]) & relevant) / len(relevant)


def mrr_at_k(ranking: list[str], labels: dict[str, int | str], k: int, policy: str) -> float | None:
    if not any(is_relevant(grade, policy) is True for grade in labels.values()):
        return None
    for index, chunk_id in enumerate(ranking[:k], start=1):
        if is_relevant(labels[chunk_id], policy) is True:
            return 1 / index
    return 0.0


def ndcg_at_k(ranking: list[str], labels: dict[str, int | str], k: int, policy: str = "graded") -> float | None:
    judged_grades = [grade for grade in labels.values() if grade != "uncertain"]
    if policy == "graded":
        gains = {chunk_id: int(grade) for chunk_id, grade in labels.items() if grade != "uncertain"}
    elif policy == "strict":
        gains = {chunk_id: 1 if grade == 2 else 0 for chunk_id, grade in labels.items() if grade != "uncertain"}
    else:
        raise ValueError(f"unknown ndcg policy: {policy}")
    ideal = sorted((2 if grade == 2 else 1 if grade == 1 else 0 for grade in judged_grades), reverse=True)[:k]
    if policy == "strict":
        ideal = sorted((1 if grade == 2 else 0 for grade in judged_grades), reverse=True)[:k]
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
    if idcg == 0:
        return None
    dcg = sum(gains.get(chunk_id, 0) / math.log2(rank + 1) for rank, chunk_id in enumerate(ranking[:k], start=1))
    return dcg / idcg


def document_hit_at_5(ranking: list[str], document_labels: dict[str, str]) -> bool | None:
    top = ranking[:5]
    if any(document_labels[chunk_id] == "yes" for chunk_id in top):
        return True
    if any(document_labels[chunk_id] == "uncertain" for chunk_id in top):
        return None
    return False


def macro(values: list[float | None]) -> float | None:
    finite = [value for value in values if value is not None]
    return round(statistics.mean(finite), 6) if finite else None


def median(values: list[float | None]) -> float | None:
    finite = [value for value in values if value is not None]
    return round(statistics.median(finite), 6) if finite else None


def rankings_for_query(traces: list[dict[str, Any]], query_id: str, system: str) -> list[str]:
    rank_field = SYSTEMS[system]["rank_field"]
    rows = [row for row in traces if row["query_id"] == query_id and row.get(rank_field) is not None]
    return [row["chunk_id"] for row in sorted(rows, key=lambda item: (item[rank_field], item["chunk_id"]))]


def validate_inputs(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]], label_summary: dict[str, Any], retrieval_summary: dict[str, Any]) -> None:
    if len(queries) != 30 or len(judgments) != 695:
        raise ValueError("expected 30 queries and 695 human judgments")
    if label_summary["reviewed"] != 695 or label_summary["pending"] != 0:
        raise ValueError("human qrels are incomplete")
    if label_summary["relevance_counts"] != EXPECTED_RELEVANCE:
        raise ValueError("human relevance totals differ from frozen checkpoint")
    if label_summary["document_relevance_counts"] != EXPECTED_DOCUMENT:
        raise ValueError("document relevance totals differ from frozen checkpoint")
    q024 = [row for row in judgments if row["query_id"] == "eval-q024"]
    q028 = [row for row in judgments if row["query_id"] == "eval-q028"]
    q030_17 = next(row for row in judgments if row["query_id"] == "eval-q030" and row["blinded_order"] == 17)
    if any(row["human_relevance"] == 2 for row in q024 + q028):
        raise ValueError("q024/q028 strict zero-qrel edge cases changed")
    if q030_17["human_relevance"] != 2 or q030_17["document_relevant"] != "no":
        raise ValueError("q030 candidate 17 edge case changed")
    frozen = retrieval_summary["frozen_retrieval_config"]
    expected = {"dense_model": "BAAI/bge-m3", "bm25_k1": 1.5, "bm25_b": 0.75, "rrf_k": 60, "reranker_model": "BAAI/bge-reranker-v2-m3"}
    for key, value in expected.items():
        if frozen.get(key) != value:
            raise ValueError(f"retrieval config mutated: {key}")
    if len(traces) != 695:
        raise ValueError("trace row count changed")


def coverage_audit(queries: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        query_rows = {}
        top5_judged = top20_judged = top5_expected = top20_expected = 0
        for query in queries:
            ranking = rankings_for_query(traces, query["query_id"], system)
            judged5 = len(ranking[:5])
            judged20 = len(ranking[:20])
            top5_judged += judged5
            top20_judged += judged20
            top5_expected += 5
            top20_expected += 20
            query_rows[query["query_id"]] = {"top5_trace_entries": judged5, "top5_judged_entries": judged5, "top20_trace_entries": judged20, "top20_judged_entries": judged20, "top20_unjudged_unknown": 20 - judged20}
        if top5_judged != top5_expected:
            raise ValueError(f"{system} top5 is not completely judged")
        by_system[system] = {
            "judged_coverage_at_5": round(top5_judged / top5_expected, 6),
            "judged_coverage_at_20": round(top20_judged / top20_expected, 6),
            "top5_judged_entries": top5_judged,
            "top5_expected_entries": top5_expected,
            "top20_judged_entries": top20_judged,
            "top20_expected_entries": top20_expected,
            "per_query": query_rows,
        }
    return by_system


def compute_metrics(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    qrels = defaultdict(dict)
    docrels = defaultdict(dict)
    for row in judgments:
        qrels[row["query_id"]][row["chunk_id"]] = row["human_relevance"]
        docrels[row["query_id"]][row["chunk_id"]] = row["document_relevant"]
    per_query = []
    for query in queries:
        row = {key: query[key] for key in ["query_id", "query_text", "query_type", "target_family", "target_regime"]}
        strict_applicable = any(grade == 2 for grade in qrels[query["query_id"]].values())
        row["strict_status"] = "eligible" if strict_applicable else "not_applicable_no_strict_relevant_qrel"
        row["systems"] = {}
        for system in SYSTEMS:
            ranking = rankings_for_query(traces, query["query_id"], system)
            labels = qrels[query["query_id"]]
            metrics = {
                "broad_precision_at_5": precision_at_k(ranking, labels, 5, "broad"),
                "broad_pooled_recall_at_5": pooled_recall_at_k(ranking, labels, 5, "broad"),
                "broad_pooled_recall_at_20": pooled_recall_at_k(ranking, labels, 20, "broad"),
                "broad_mrr_at_5": mrr_at_k(ranking, labels, 5, "broad"),
                "graded_ndcg_at_5": ndcg_at_k(ranking, labels, 5, "graded"),
                "document_hit_at_5": document_hit_at_5(ranking, docrels[query["query_id"]]),
                "strict_precision_at_5": precision_at_k(ranking, labels, 5, "strict"),
                "strict_pooled_recall_at_5": pooled_recall_at_k(ranking, labels, 5, "strict"),
                "strict_mrr_at_5": mrr_at_k(ranking, labels, 5, "strict"),
                "strict_binary_ndcg_at_5": ndcg_at_k(ranking, labels, 5, "strict"),
                "judged_top20": len(ranking[:20]),
                "flags": [],
            }
            if metrics["strict_pooled_recall_at_5"] is None:
                metrics["flags"].append("no_strict_qrels")
            if metrics["judged_top20"] < 20:
                metrics["flags"].append("low_judged_coverage_at_20")
            if metrics["broad_precision_at_5"] == 0:
                metrics["flags"].append("zero_relevant_top5")
            if metrics["document_hit_at_5"] is True and metrics["broad_precision_at_5"] < 0.4:
                metrics["flags"].append("document_hit_but_poor_chunk_score")
            if query["query_type"] == "hard_ambiguous" and metrics["broad_precision_at_5"] < 0.6:
                metrics["flags"].append("composite_query_failure")
            row["systems"][system] = metrics
        per_query.append(row)
    return per_query, aggregate_metrics(queries, per_query)


def aggregate_metrics(queries: list[dict[str, Any]], per_query: list[dict[str, Any]]) -> dict[str, Any]:
    query_by_id = {query["query_id"]: query for query in queries}
    overall = {}
    for system in SYSTEMS:
        rows = [row["systems"][system] for row in per_query]
        overall[system] = {
            "label": SYSTEMS[system]["label"],
            "broad_precision_at_5": macro([row["broad_precision_at_5"] for row in rows]),
            "broad_precision_at_5_median": median([row["broad_precision_at_5"] for row in rows]),
            "broad_pooled_recall_at_5": macro([row["broad_pooled_recall_at_5"] for row in rows]),
            "broad_pooled_recall_at_20": macro([row["broad_pooled_recall_at_20"] for row in rows]),
            "broad_mrr_at_5": macro([row["broad_mrr_at_5"] for row in rows]),
            "graded_ndcg_at_5": macro([row["graded_ndcg_at_5"] for row in rows]),
            "document_hit_at_5": macro([None if row["document_hit_at_5"] is None else float(row["document_hit_at_5"]) for row in rows]),
            "strict_precision_at_5": macro([row["strict_precision_at_5"] for row in rows]),
            "strict_pooled_recall_at_5": macro([row["strict_pooled_recall_at_5"] for row in rows]),
            "strict_mrr_at_5": macro([row["strict_mrr_at_5"] for row in rows]),
            "strict_binary_ndcg_at_5": macro([row["strict_binary_ndcg_at_5"] for row in rows]),
            "strict_eligible_query_count": sum(1 for row in rows if row["strict_pooled_recall_at_5"] is not None),
        }
    by_query_type = grouped_averages(per_query, "query_type")
    by_family = grouped_averages(per_query, "target_family")
    by_regime = grouped_averages(per_query, "target_regime")
    deltas = rerank_deltas(per_query)
    bootstrap = bootstrap_deltas(per_query)
    return {"overall": overall, "by_query_type": by_query_type, "by_family": by_family, "by_regime": by_regime, "deltas": deltas, "bootstrap": bootstrap, "query_count": len(query_by_id)}


def grouped_averages(per_query: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_query:
        groups[row[field]].append(row)
    result = {}
    for group, rows in sorted(groups.items()):
        result[group] = {"query_count": len(rows), "systems": {}}
        for system in SYSTEMS:
            values = [row["systems"][system] for row in rows]
            result[group]["systems"][system] = {
                "broad_precision_at_5": macro([value["broad_precision_at_5"] for value in values]),
                "broad_pooled_recall_at_5": macro([value["broad_pooled_recall_at_5"] for value in values]),
                "broad_mrr_at_5": macro([value["broad_mrr_at_5"] for value in values]),
                "graded_ndcg_at_5": macro([value["graded_ndcg_at_5"] for value in values]),
            }
    return result


def rerank_deltas(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5", "graded_ndcg_at_5"]
    output = {}
    for metric in metrics:
        deltas = []
        for row in per_query:
            before = row["systems"]["hybrid"][metric]
            after = row["systems"]["hybrid_rerank"][metric]
            if before is not None and after is not None:
                deltas.append((row["query_id"], after - before))
        output[metric] = {
            "improved_queries": [query_id for query_id, delta in deltas if delta > 0],
            "worsened_queries": [query_id for query_id, delta in deltas if delta < 0],
            "unchanged_queries": [query_id for query_id, delta in deltas if delta == 0],
            "mean_delta": round(statistics.mean(delta for _, delta in deltas), 6) if deltas else None,
        }
    return output


def bootstrap_deltas(per_query: list[dict[str, Any]], samples: int = 10000, seed: int = 20260907) -> dict[str, Any]:
    comparisons = [("hybrid", "dense"), ("hybrid_rerank", "hybrid")]
    metrics = ["broad_precision_at_5", "graded_ndcg_at_5", "broad_mrr_at_5"]
    rng = random.Random(seed)
    output = {"samples": samples, "seed": seed, "comparisons": {}}
    for left, right in comparisons:
        key = f"{left}_minus_{right}"
        output["comparisons"][key] = {}
        for metric in metrics:
            diffs = [row["systems"][left][metric] - row["systems"][right][metric] for row in per_query if row["systems"][left][metric] is not None and row["systems"][right][metric] is not None]
            draws = []
            for _ in range(samples):
                sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
                draws.append(statistics.mean(sample))
            draws.sort()
            output["comparisons"][key][metric] = {"mean_delta": round(statistics.mean(diffs), 6), "ci95": [round(draws[int(samples * 0.025)], 6), round(draws[int(samples * 0.975) - 1], 6)]}
    return output


def write_results_doc(results: dict[str, Any], coverage: dict[str, Any], per_query: list[dict[str, Any]]) -> None:
    overall = results["overall"]
    lines = [
        "# Retrieval Evaluation Results",
        "",
        "## Benchmark Snapshot",
        "",
        "- queries: 30",
        "- human judgments: 695",
        "- corpus: 70 trusted judgments / 1356 chunks",
        "",
        "## Systems",
        "",
        "- BM25: legalai-bm25-index-v1, k1=1.5, b=0.75",
        "- Dense: BAAI/bge-m3, legalai-chroma-index-v1",
        "- Hybrid: RRF, K=60",
        "- Hybrid+Rerank: hybrid RRF plus BAAI/bge-reranker-v2-m3, max_length=512",
        "",
        "## Relevance Policies",
        "",
        "Broad relevance treats grades 1 and 2 as relevant. Strict relevance treats only grade 2 as relevant. Graded nDCG@5 uses gain / log2(rank + 1), with gains 2, 1, and 0.",
        "",
        "## Judged Coverage",
        "",
        "| System | @5 | @20 |",
        "|---|---:|---:|",
    ]
    for system, data in coverage.items():
        lines.append(f"| {SYSTEMS[system]['label']} | {data['judged_coverage_at_5']:.3f} | {data['judged_coverage_at_20']:.3f} |")
    lines.extend(["", "## Overall Metrics", "", system_table(overall), "", "## Query-Type Breakdown", ""])
    for query_type, data in results["by_query_type"].items():
        lines.extend([f"### {query_type}", "", f"queries: {data['query_count']}", "", system_table(data["systems"]), ""])
    lines.extend(["## Regime Diagnostics", ""])
    for regime, data in results["by_regime"].items():
        lines.extend([f"### {regime}", "", f"queries: {data['query_count']}", "", system_table(data["systems"], compact=True), ""])
    lines.extend(["## Family Diagnostics", ""])
    for family, data in results["by_family"].items():
        lines.extend([f"### {family}", "", f"queries: {data['query_count']}", "", system_table(data["systems"], compact=True), ""])
    delta = results["deltas"]["broad_precision_at_5"]
    lines.extend([
        "## Reranker Delta Analysis",
        "",
        f"- Broad Precision@5 improved queries: {len(delta['improved_queries'])}",
        f"- Broad Precision@5 worsened queries: {len(delta['worsened_queries'])}",
        f"- Broad Precision@5 unchanged queries: {len(delta['unchanged_queries'])}",
        f"- Broad Precision@5 mean rerank delta: {delta['mean_delta']}",
        "- Metric deltas are descriptive paired differences, not significance claims.",
        "",
        "## Per-Query Comparison",
        "",
        per_query_table(per_query),
        "",
        "## Difficult Query Analysis",
        "",
        "- eval-q001 tests Section 302 murder retrieval and shows high sensitivity to chunk-level ranking.",
        "- eval-q009 tests Section 323 hurt retrieval and has sparse direct relevance.",
        "- eval-q024 has no grade-2 qrels, so strict recall/nDCG are not applicable for that query.",
        "- eval-q026 and eval-q027 represent IPC/BNS/BNSS transition cases with small judged pools.",
        "- eval-q028 has no grade-2 qrels and should be read as a composite-query coverage diagnostic.",
        "",
        "## Statistical Uncertainty",
        "",
        "A deterministic paired bootstrap with 10,000 resamples is included in retrieval_eval_bootstrap.json. Confidence intervals are descriptive and should not be overread as proof of significance.",
        "",
        "## Limitations",
        "",
        "- trusted corpus contains only 70 judgments / 1356 chunks",
        "- evaluation pool is pooled, not exhaustive",
        "- Recall is pooled recall",
        "- top20 may contain unjudged candidates",
        "- human labels are from one reviewer",
        "- n=30 queries is relatively small",
        "- transition-law subsets are especially small",
        "- benchmark was built from the existing corpus",
        "- this is retrieval evaluation, not answer-generation evaluation",
    ])
    RESULTS_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def per_query_table(per_query: list[dict[str, Any]]) -> str:
    header = "| Query | Type | BM25 P/R20/nDCG | Dense P/R20/nDCG | Hybrid P/R20/nDCG | Rerank P/R20/nDCG | Flags |"
    sep = "|---|---|---:|---:|---:|---:|---|"
    rows = []
    for row in per_query:
        flags = sorted({flag for system in row["systems"].values() for flag in system["flags"]})
        system_cells = []
        for system in SYSTEMS:
            metrics = row["systems"][system]
            system_cells.append(f"{metrics['broad_precision_at_5']:.2f}/{metrics['broad_pooled_recall_at_20']:.2f}/{metrics['graded_ndcg_at_5']:.2f}")
        rows.append(f"| {row['query_id']} | {row['query_type']} | {' | '.join(system_cells)} | {', '.join(flags) or 'none'} |")
    return "\n".join([header, sep, *rows])


def system_table(data: dict[str, Any], compact: bool = False) -> str:
    if compact:
        header = "| System | P@5 Broad | nDCG@5 |"
        sep = "|---|---:|---:|"
        rows = [f"| {SYSTEMS[system]['label']} | {values['broad_precision_at_5']:.3f} | {values['graded_ndcg_at_5']:.3f} |" for system, values in data.items()]
        return "\n".join([header, sep, *rows])
    header = "| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    rows = []
    for system, values in data.items():
        rows.append(
            f"| {SYSTEMS[system]['label']} | {fmt(values['broad_precision_at_5'])} | {fmt(values.get('broad_pooled_recall_at_5'))} | {fmt(values.get('broad_pooled_recall_at_20'))} | {fmt(values.get('broad_mrr_at_5'))} | {fmt(values.get('graded_ndcg_at_5'))} | {fmt(values.get('document_hit_at_5'))} | {fmt(values.get('strict_precision_at_5'))} | {fmt(values.get('strict_pooled_recall_at_5'))} | {fmt(values.get('strict_mrr_at_5'))} | {fmt(values.get('strict_binary_ndcg_at_5'))} |"
        )
    return "\n".join([header, sep, *rows])


def fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    label_summary = json.loads(HUMAN_LABEL_SUMMARY_PATH.read_text(encoding="utf-8"))
    retrieval_summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    validate_inputs(queries, judgments, traces, label_summary, retrieval_summary)
    coverage = coverage_audit(queries, traces)
    per_query, results = compute_metrics(queries, judgments, traces)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_QUERY_PATH.write_text(json.dumps(per_query, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    COVERAGE_PATH.write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    BOOTSTRAP_PATH.write_text(json.dumps(results["bootstrap"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_results_doc(results, coverage, per_query)
    print(json.dumps({"overall": results["overall"], "coverage": {system: {"at5": row["judged_coverage_at_5"], "at20": row["judged_coverage_at_20"]} for system, row in coverage.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
