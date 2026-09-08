"""Analyze the untuned retrieval baseline on the frozen development set."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.analyze_retrieval_eval import (
    SYSTEMS,
    aggregate_metrics,
    bootstrap_deltas,
    coverage_audit,
    compute_metrics,
)
from backend.scripts.analyze_retrieval_errors import overlap_analysis
from backend.scripts.build_retrieval_dev_set import DEV_JUDGMENTS_PATH, DEV_QUERIES_PATH, DEV_SUMMARY_PATH, DEV_TRACES_PATH, DEV_VERSION
from backend.scripts.materialize_retrieval_dev_labels import SUMMARY_PATH as DEV_LABEL_SUMMARY_PATH

MANIFEST_DIR = DEV_SUMMARY_PATH.parent
DEV_RESULTS_PATH = MANIFEST_DIR / "retrieval_dev_results.json"
DEV_PER_QUERY_PATH = MANIFEST_DIR / "retrieval_dev_per_query_metrics.json"
DEV_COVERAGE_PATH = MANIFEST_DIR / "retrieval_dev_judged_coverage.json"
DEV_OVERLAP_PATH = MANIFEST_DIR / "retrieval_dev_candidate_overlap.json"
DEV_BOOTSTRAP_PATH = MANIFEST_DIR / "retrieval_dev_bootstrap.json"
DEV_RESULTS_DOC = DEV_SUMMARY_PATH.parents[3] / "docs/RETRIEVAL_DEV_BASELINE_RESULTS.md"

EXPECTED_RELEVANCE = {"grade_2": 103, "grade_1": 174, "grade_0": 197, "uncertain": 0}
EXPECTED_DOCUMENT = {"yes": 260, "no": 214, "uncertain": 0}
IMPORTANT_QUERIES = ["dev-q001", "dev-q002", "dev-q003", "dev-q004", "dev-q006", "dev-q007", "dev-q010", "dev-q012", "dev-q016", "dev-q019"]


def validate_inputs(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]], label_summary: dict[str, Any]) -> None:
    if len(queries) != 20 or len(judgments) != 474 or len(traces) != 474:
        raise ValueError("expected 20 dev queries, 474 judgments, and 474 traces")
    if any(query["development_version"] != DEV_VERSION for query in queries):
        raise ValueError("development version mismatch")
    if label_summary["reviewed"] != 474 or label_summary["pending"] != 0:
        raise ValueError("dev labels are incomplete")
    if label_summary["human_relevance_counts"] != EXPECTED_RELEVANCE:
        raise ValueError("dev relevance totals changed")
    if label_summary["document_relevance_counts"] != EXPECTED_DOCUMENT:
        raise ValueError("dev document relevance totals changed")
    for query_id in ["dev-q006", "dev-q007"]:
        if any(row["query_id"] == query_id and row["human_relevance"] == 2 for row in judgments):
            raise ValueError(f"{query_id} zero-strict-qrel edge case changed")


def build_qrels(judgments: list[dict[str, Any]]) -> dict[str, dict[str, int | str]]:
    qrels: dict[str, dict[str, int | str]] = defaultdict(dict)
    for row in judgments:
        qrels[row["query_id"]][row["chunk_id"]] = row["human_relevance"]
    return qrels


def focus_breakdown(queries: list[dict[str, Any]], per_query: list[dict[str, Any]]) -> dict[str, Any]:
    rows = {row["query_id"]: row for row in per_query}
    by_focus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        for focus in query["tuning_focus"]:
            by_focus[focus].append(rows[query["query_id"]])
    result = {}
    for focus, group in sorted(by_focus.items()):
        result[focus] = {"query_count": len(group), "systems": {}}
        for system in SYSTEMS:
            values = [row["systems"][system] for row in group]
            result[focus]["systems"][system] = {
                "broad_precision_at_5": mean(v["broad_precision_at_5"] for v in values),
                "broad_mrr_at_5": mean(v["broad_mrr_at_5"] for v in values),
                "graded_ndcg_at_5": mean(v["graded_ndcg_at_5"] for v in values),
            }
    return result


def mean(values: Any) -> float:
    return round(statistics.mean(list(values)), 6)


def rerank_delta(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for metric in ["broad_precision_at_5", "strict_precision_at_5", "graded_ndcg_at_5", "broad_mrr_at_5"]:
        rows = []
        for row in per_query:
            delta = row["systems"]["hybrid_rerank"][metric] - row["systems"]["hybrid"][metric]
            rows.append((row["query_id"], delta))
        output[metric] = {
            "improved": [qid for qid, delta in rows if delta > 0],
            "worsened": [qid for qid, delta in rows if delta < 0],
            "unchanged": [qid for qid, delta in rows if delta == 0],
            "mean_delta": round(statistics.mean(delta for _, delta in rows), 6),
        }
    return output


def difficult_query_notes(per_query: list[dict[str, Any]], judgments: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    rows = {row["query_id"]: row for row in per_query}
    qrels = defaultdict(list)
    for row in judgments:
        qrels[row["query_id"]].append(row)
    notes = {}
    for query_id in IMPORTANT_QUERIES:
        row = rows[query_id]
        broad = sum(j["human_relevance"] in {1, 2} for j in qrels[query_id])
        strict = sum(j["human_relevance"] == 2 for j in qrels[query_id])
        notes[query_id] = {
            "broad_relevant_qrels": broad,
            "strict_qrels": strict,
            "system_top5_broad_precision": {system: row["systems"][system]["broad_precision_at_5"] for system in SYSTEMS},
            "system_top5_strict_precision": {system: row["systems"][system]["strict_precision_at_5"] for system in SYSTEMS},
            "system_ndcg_at_5": {system: row["systems"][system]["graded_ndcg_at_5"] for system in SYSTEMS},
            "document_hit_at_5": {system: row["systems"][system]["document_hit_at_5"] for system in SYSTEMS},
            "judged_top20": {system: coverage[system]["per_query"][query_id]["top20_judged_entries"] for system in SYSTEMS},
            "observed_baseline_weakness": weakness(row),
        }
    return notes


def weakness(row: dict[str, Any]) -> str:
    best = max(row["systems"][system]["broad_precision_at_5"] for system in SYSTEMS)
    if row["strict_status"] != "eligible":
        return "no strict grade-2 qrels in development pool"
    if best < 0.6:
        return "low broad top5 precision across systems"
    if min(row["systems"][system]["judged_top20"] for system in SYSTEMS) < 20:
        return "top20 judged coverage is censored"
    return "no severe top5 baseline weakness"


def write_doc(payload: dict[str, Any]) -> None:
    results = payload["results"]
    coverage = payload["coverage"]
    overlap = payload["candidate_overlap"]
    lines = [
        "# Retrieval Development Baseline Results",
        "",
        "## Development-Set Snapshot",
        "",
        "- queries: 20",
        "- human judgments: 474",
        "- development version: `legalai-retrieval-dev-v1`",
        "",
        "## Systems",
        "",
        "- BM25: legalai-bm25-index-v1, k1=1.5, b=0.75",
        "- Dense: BAAI/bge-m3, legalai-chroma-index-v1",
        "- Hybrid: RRF K=60",
        "- Hybrid+Rerank: Hybrid RRF plus BAAI/bge-reranker-v2-m3, max_length=512",
        "",
        "## Relevance Policies",
        "",
        "Broad relevance is grade 1 or 2. Strict relevance is grade 2 only. Graded nDCG uses the frozen benchmark convention: gain / log2(rank + 1).",
        "",
        "## Judged Coverage",
        "",
        "| System | @5 | @20 |",
        "|---|---:|---:|",
    ]
    for system, row in coverage.items():
        lines.append(f"| {SYSTEMS[system]['label']} | {row['judged_coverage_at_5']:.3f} | {row['judged_coverage_at_20']:.3f} |")
    lines.extend(["", "## Overall Metric Table", "", system_table(results["overall"]), "", "## Query-Type Breakdown", ""])
    for query_type, row in results["by_query_type"].items():
        lines.extend([f"### {query_type}", "", f"queries: {row['query_count']}", "", system_table(row["systems"], compact=True), ""])
    lines.extend(["## Tuning-Focus Breakdown", "", "Focus groups overlap and are not mutually exclusive.", ""])
    for focus, row in payload["tuning_focus_breakdown"].items():
        lines.extend([f"### {focus}", "", f"queries: {row['query_count']}", "", system_table(row["systems"], compact=True), ""])
    p5 = payload["rerank_delta"]["broad_precision_at_5"]
    ndcg = payload["rerank_delta"]["graded_ndcg_at_5"]
    lines.extend([
        "## Reranker Delta",
        "",
        f"- Broad P@5 improved/worsened/unchanged: {len(p5['improved'])}/{len(p5['worsened'])}/{len(p5['unchanged'])}",
        f"- Broad P@5 mean delta: {p5['mean_delta']}",
        f"- Graded nDCG@5 mean delta: {ndcg['mean_delta']}",
        "",
        "## Candidate Complementarity",
        "",
        f"- broad BM25 relevant top20: {overlap['aggregate']['broad']['bm25_relevant_top20']}",
        f"- broad Dense relevant top20: {overlap['aggregate']['broad']['dense_relevant_top20']}",
        f"- broad intersection: {overlap['aggregate']['broad']['intersection']}",
        f"- broad BM25-only: {overlap['aggregate']['broad']['bm25_only']}",
        f"- broad Dense-only: {overlap['aggregate']['broad']['dense_only']}",
        f"- broad union: {overlap['aggregate']['broad']['union']}",
        "",
        "## Difficult-Query Observations",
        "",
    ])
    for query_id, row in payload["difficult_queries"].items():
        lines.append(f"- {query_id}: {row['observed_baseline_weakness']}; broad qrels={row['broad_relevant_qrels']}, strict qrels={row['strict_qrels']}.")
    lines.extend([
        "",
        "## Development-Set Caveat",
        "",
        "THIS DEVELOPMENT SET IS FOR TUNING. Future variants may be selected using this dev-set performance. Dev-set gains are not unbiased final performance estimates; the original 30-query frozen benchmark remains the baseline reference set for later post-tuning evaluation.",
        "",
        "## Limitations",
        "",
        "- only 20 dev queries",
        "- same 70-judgment / 1356-chunk trusted corpus",
        "- pooled qrels are non-exhaustive",
        "- top20 may be censored",
        "- one human reviewer",
        "- dev set intentionally emphasizes known weak areas",
        "- this set is for tuning, not unbiased final reporting",
        "- retrieval only, not answer generation",
    ])
    DEV_RESULTS_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def system_table(data: dict[str, Any], compact: bool = False) -> str:
    if compact:
        lines = ["| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |", "|---|---:|---:|---:|---:|"]
        for system, row in data.items():
            lines.append(f"| {SYSTEMS[system]['label']} | {fmt(row['broad_precision_at_5'])} | {fmt(row.get('broad_pooled_recall_at_5'))} | {fmt(row.get('broad_mrr_at_5'))} | {fmt(row.get('graded_ndcg_at_5'))} |")
        return "\n".join(lines)
    lines = ["| Metric | BM25 | Dense | Hybrid | Hybrid+Rerank |", "|---|---:|---:|---:|---:|"]
    metrics = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5", "graded_ndcg_at_5", "document_hit_at_5", "strict_precision_at_5", "strict_pooled_recall_at_5", "strict_pooled_recall_at_20", "strict_mrr_at_5", "strict_binary_ndcg_at_5"]
    for metric in metrics:
        lines.append(f"| {metric} | " + " | ".join(fmt(data[system].get(metric)) for system in SYSTEMS) + " |")
    return "\n".join(lines)


def fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def main() -> int:
    queries = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(DEV_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(DEV_TRACES_PATH.read_text(encoding="utf-8"))
    label_summary = json.loads(DEV_LABEL_SUMMARY_PATH.read_text(encoding="utf-8"))
    validate_inputs(queries, judgments, traces, label_summary)
    coverage = coverage_audit(queries, traces)
    per_query, results = compute_metrics(queries, judgments, traces)
    qrels = build_qrels(judgments)
    overlap = overlap_analysis(queries, traces, qrels)
    results["tuning_focus_breakdown"] = focus_breakdown(queries, per_query)
    results["rerank_delta"] = rerank_delta(per_query)
    results["bootstrap"] = bootstrap_deltas(per_query)
    payload = {
        "development_version": DEV_VERSION,
        "query_count": len(queries),
        "judgment_count": len(judgments),
        "results": results,
        "coverage": coverage,
        "candidate_overlap": overlap,
        "tuning_focus_breakdown": results["tuning_focus_breakdown"],
        "rerank_delta": results["rerank_delta"],
        "difficult_queries": difficult_query_notes(per_query, judgments, coverage),
        "metric_status": "untuned_dev_baseline_complete",
    }
    DEV_RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_PER_QUERY_PATH.write_text(json.dumps(per_query, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_COVERAGE_PATH.write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_OVERLAP_PATH.write_text(json.dumps(overlap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_BOOTSTRAP_PATH.write_text(json.dumps(results["bootstrap"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(payload)
    print(json.dumps({"overall": results["overall"], "coverage": {system: {"at5": row["judged_coverage_at_5"], "at20": row["judged_coverage_at_20"]} for system, row in coverage.items()}, "rerank_delta": results["rerank_delta"]["broad_precision_at_5"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
