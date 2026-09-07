"""Diagnose frozen retrieval benchmark errors without tuning retrieval."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.analyze_retrieval_eval import SYSTEMS, rankings_for_query
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, QUERIES_PATH, SUMMARY_PATH, TRACES_PATH
from backend.scripts.materialize_retrieval_eval_labels import HUMAN_LABEL_SUMMARY_PATH

MANIFEST_DIR = SUMMARY_PATH.parent
RESULTS_PATH = MANIFEST_DIR / "retrieval_eval_results.json"
PER_QUERY_METRICS_PATH = MANIFEST_DIR / "retrieval_eval_per_query_metrics.json"
COVERAGE_PATH = MANIFEST_DIR / "retrieval_eval_judged_coverage.json"
ERROR_ANALYSIS_PATH = MANIFEST_DIR / "retrieval_eval_error_analysis.json"
CANDIDATE_OVERLAP_PATH = MANIFEST_DIR / "retrieval_eval_candidate_overlap.json"
RERANK_DELTAS_PATH = MANIFEST_DIR / "retrieval_eval_rerank_deltas.json"
ERROR_DOC = SUMMARY_PATH.parents[3] / "docs/RETRIEVAL_ERROR_ANALYSIS.md"
TUNING_DOC = SUMMARY_PATH.parents[3] / "docs/RETRIEVAL_TUNING_DECISION.md"

REQUIRED_QUERIES = {"eval-q001", "eval-q009", "eval-q016", "eval-q024", "eval-q025", "eval-q026", "eval-q027", "eval-q028"}
ALLOWED_FAILURES = {
    "candidate_generation_lexical",
    "candidate_generation_dense",
    "candidate_generation_both",
    "fusion_ordering",
    "reranker_ordering",
    "chunk_quality",
    "query_ambiguity",
    "legal_regime_resolution",
    "benchmark_pool_limitation",
    "no_material_failure",
    "mixed",
}


def relevant(grade: int | str, strict: bool = False) -> bool:
    return grade == 2 if strict else grade in {1, 2}


def validate_freeze(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], label_summary: dict[str, Any], results: dict[str, Any]) -> None:
    expected_p5 = {"bm25": 0.833333, "dense": 0.86, "hybrid": 0.873333, "hybrid_rerank": 0.873333}
    expected_ndcg = {"bm25": 0.727987, "dense": 0.785689, "hybrid": 0.787465, "hybrid_rerank": 0.819445}
    if len(queries) != 30 or len(judgments) != 695:
        raise ValueError("expected 30 queries and 695 judgments")
    if label_summary["reviewed"] != 695 or label_summary["pending"] != 0:
        raise ValueError("human labels are not complete")
    for system, value in expected_p5.items():
        if round(results["overall"][system]["broad_precision_at_5"], 6) != value:
            raise ValueError(f"{system} broad P@5 changed")
    for system, value in expected_ndcg.items():
        if round(results["overall"][system]["graded_ndcg_at_5"], 6) != value:
            raise ValueError(f"{system} broad nDCG@5 changed")


def build_qrels(judgments: list[dict[str, Any]]) -> tuple[dict[str, dict[str, int | str]], dict[str, dict[str, str]]]:
    qrels: dict[str, dict[str, int | str]] = defaultdict(dict)
    docrels: dict[str, dict[str, str]] = defaultdict(dict)
    for row in judgments:
        qrels[row["query_id"]][row["chunk_id"]] = row["human_relevance"]
        docrels[row["query_id"]][row["chunk_id"]] = row["document_relevant"]
    return qrels, docrels


def overlap_analysis(queries: list[dict[str, Any]], traces: list[dict[str, Any]], qrels: dict[str, dict[str, int | str]]) -> dict[str, Any]:
    per_query: dict[str, Any] = {}
    aggregate = {"broad": Counter(), "strict": Counter()}
    for query in queries:
        query_id = query["query_id"]
        bm25 = set(rankings_for_query(traces, query_id, "bm25")[:20])
        dense = set(rankings_for_query(traces, query_id, "dense")[:20])
        for mode, strict in [("broad", False), ("strict", True)]:
            rel = {chunk_id for chunk_id, grade in qrels[query_id].items() if relevant(grade, strict)}
            both = rel & bm25 & dense
            bm25_only = (rel & bm25) - dense
            dense_only = (rel & dense) - bm25
            neither = rel - (bm25 | dense)
            data = {
                "relevant_total": len(rel),
                "bm25_relevant_top20": len(rel & bm25),
                "dense_relevant_top20": len(rel & dense),
                "intersection": len(both),
                "union": len(rel & (bm25 | dense)),
                "bm25_only": len(bm25_only),
                "dense_only": len(dense_only),
                "neither": len(neither),
            }
            per_query.setdefault(query_id, {})[mode] = data
            for key, value in data.items():
                aggregate[mode][key] += value
    return {"per_query": per_query, "aggregate": {mode: dict(counts) for mode, counts in aggregate.items()}}


def rerank_analysis(per_query_metrics: list[dict[str, Any]], traces: list[dict[str, Any]], qrels: dict[str, dict[str, int | str]]) -> dict[str, Any]:
    per_query = {}
    status_counts = Counter()
    for row in per_query_metrics:
        query_id = row["query_id"]
        hybrid = rankings_for_query(traces, query_id, "hybrid")
        rerank = rankings_for_query(traces, query_id, "hybrid_rerank")
        h5, r5 = set(hybrid[:5]), set(rerank[:5])
        promoted = sorted(chunk for chunk in (r5 - h5) if relevant(qrels[query_id][chunk]))
        dropped = sorted(chunk for chunk in (h5 - r5) if relevant(qrels[query_id][chunk]))
        grade2_promoted = sorted(chunk for chunk in promoted if qrels[query_id][chunk] == 2)
        grade2_demoted = sorted(chunk for chunk in dropped if qrels[query_id][chunk] == 2)
        p_delta = row["systems"]["hybrid_rerank"]["broad_precision_at_5"] - row["systems"]["hybrid"]["broad_precision_at_5"]
        ndcg_delta = row["systems"]["hybrid_rerank"]["graded_ndcg_at_5"] - row["systems"]["hybrid"]["graded_ndcg_at_5"]
        strict_delta = row["systems"]["hybrid_rerank"]["strict_precision_at_5"] - row["systems"]["hybrid"]["strict_precision_at_5"]
        status = "reranker_helpful" if ndcg_delta > 0.01 or p_delta > 0 else "reranker_harmful" if ndcg_delta < -0.01 or p_delta < 0 else "reranker_neutral"
        status_counts[status] += 1
        per_query[query_id] = {
            "status": status,
            "relevant_promoted_into_top5": promoted,
            "relevant_dropped_from_top5": dropped,
            "grade2_promoted_into_top5": grade2_promoted,
            "grade2_demoted_from_top5": grade2_demoted,
            "broad_precision_at_5_delta": round(p_delta, 6),
            "graded_ndcg_at_5_delta": round(ndcg_delta, 6),
            "strict_precision_at_5_delta": round(strict_delta, 6),
            "shared_candidate_rank_movements": rank_movements(hybrid, rerank),
        }
    return {"per_query": per_query, "summary": dict(status_counts)}


def rank_movements(before: list[str], after: list[str]) -> list[dict[str, Any]]:
    before_rank = {chunk_id: rank for rank, chunk_id in enumerate(before, start=1)}
    after_rank = {chunk_id: rank for rank, chunk_id in enumerate(after, start=1)}
    rows = []
    for chunk_id in sorted(set(before_rank) & set(after_rank)):
        rows.append({"chunk_id": chunk_id, "hybrid_rank": before_rank[chunk_id], "rerank_rank": after_rank[chunk_id], "delta": before_rank[chunk_id] - after_rank[chunk_id]})
    return rows


def chunk_quality(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    by_chunk = {(row["query_id"], row["chunk_id"]): row for row in judgments}
    overall = Counter()
    per_query: dict[str, Counter[str]] = defaultdict(Counter)
    top5: dict[str, Counter[str]] = {system: Counter() for system in SYSTEMS}
    for row in judgments:
        flags = quality_flags(row)
        overall.update(flags)
        per_query[row["query_id"]].update(flags)
    for query in queries:
        for system in SYSTEMS:
            for chunk_id in rankings_for_query(traces, query["query_id"], system)[:5]:
                top5[system].update(quality_flags(by_chunk[(query["query_id"], chunk_id)]))
    return {
        "overall": dict(overall),
        "per_query": {query_id: dict(counts) for query_id, counts in sorted(per_query.items())},
        "top5_by_system": {system: dict(counts) for system, counts in top5.items()},
    }


def quality_flags(row: dict[str, Any]) -> list[str]:
    flags = []
    if row["document_relevant"] == "yes" and row["human_relevance"] == 0:
        flags.append("right_document_wrong_chunk")
    if row["document_relevant"] == "no" and row["human_relevance"] in {1, 2}:
        flags.append("wrong_document_useful_chunk")
    return flags


def classify_queries(
    queries: list[dict[str, Any]],
    qrels: dict[str, dict[str, int | str]],
    overlap: dict[str, Any],
    rerank: dict[str, Any],
    per_query_metrics: list[dict[str, Any]],
    quality: dict[str, Any],
) -> dict[str, Any]:
    metric_by_query = {row["query_id"]: row for row in per_query_metrics}
    diagnostics = {}
    for query in queries:
        query_id = query["query_id"]
        broad = overlap["per_query"][query_id]["broad"]
        strict = overlap["per_query"][query_id]["strict"]
        hybrid_p5 = metric_by_query[query_id]["systems"]["hybrid"]["broad_precision_at_5"]
        rerank_p5 = metric_by_query[query_id]["systems"]["hybrid_rerank"]["broad_precision_at_5"]
        failures = []
        if broad["union"] < max(1, broad["relevant_total"] // 2):
            failures.append("candidate_generation_both")
        elif broad["bm25_relevant_top20"] < broad["dense_relevant_top20"] - 2:
            failures.append("candidate_generation_lexical")
        elif broad["dense_relevant_top20"] < broad["bm25_relevant_top20"] - 2:
            failures.append("candidate_generation_dense")
        if hybrid_p5 < max(metric_by_query[query_id]["systems"]["bm25"]["broad_precision_at_5"], metric_by_query[query_id]["systems"]["dense"]["broad_precision_at_5"]):
            failures.append("fusion_ordering")
        if rerank["per_query"][query_id]["status"] == "reranker_harmful":
            failures.append("reranker_ordering")
        if quality["per_query"].get(query_id, {}).get("right_document_wrong_chunk", 0):
            failures.append("chunk_quality")
        if query["query_type"] == "hard_ambiguous":
            failures.append("query_ambiguity")
        if query["target_regime"] in {"bns_bnss", "mixed_or_transition"}:
            failures.append("legal_regime_resolution")
        if strict["relevant_total"] == 0 or any(row["systems"]["hybrid"]["judged_top20"] < 20 for row in [metric_by_query[query_id]]):
            failures.append("benchmark_pool_limitation")
        if not failures:
            failures.append("no_material_failure")
        primary = choose_primary(failures)
        diagnostics[query_id] = {
            "query_text": query["query_text"],
            "query_type": query["query_type"],
            "target_family": query["target_family"],
            "target_regime": query["target_regime"],
            "broad_relevant_count": broad["relevant_total"],
            "strict_relevant_count": strict["relevant_total"],
            "bm25_relevant_coverage_top20": broad["bm25_relevant_top20"],
            "dense_relevant_coverage_top20": broad["dense_relevant_top20"],
            "hybrid_top5_quality": hybrid_p5,
            "reranked_top5_quality": rerank_p5,
            "judged_coverage_caveat": metric_by_query[query_id]["systems"]["hybrid"]["judged_top20"] < 20,
            "primary_failure": primary,
            "secondary_failures": [failure for failure in failures if failure != primary],
            "evidence": evidence_sentence(query_id, broad, strict, metric_by_query[query_id], rerank["per_query"][query_id], quality["per_query"].get(query_id, {})),
            "confidence": "medium" if primary != "no_material_failure" else "high",
            "tuning_could_plausibly_help": primary in {"candidate_generation_lexical", "candidate_generation_dense", "candidate_generation_both", "fusion_ordering", "reranker_ordering", "legal_regime_resolution", "mixed"},
        }
        if diagnostics[query_id]["primary_failure"] not in ALLOWED_FAILURES:
            raise ValueError(f"invalid taxonomy class: {diagnostics[query_id]['primary_failure']}")
    return diagnostics


def choose_primary(failures: list[str]) -> str:
    priority = ["candidate_generation_both", "legal_regime_resolution", "reranker_ordering", "fusion_ordering", "chunk_quality", "query_ambiguity", "benchmark_pool_limitation", "candidate_generation_lexical", "candidate_generation_dense", "no_material_failure"]
    selected = [failure for failure in priority if failure in failures]
    if len(set(failures) - {"benchmark_pool_limitation"}) > 2:
        return "mixed"
    return selected[0]


def evidence_sentence(query_id: str, broad: dict[str, int], strict: dict[str, int], metrics: dict[str, Any], rerank: dict[str, Any], quality: dict[str, int]) -> str:
    return (
        f"{query_id}: broad relevant {broad['relevant_total']}, strict relevant {strict['relevant_total']}; "
        f"BM25/Dense top20 broad relevant {broad['bm25_relevant_top20']}/{broad['dense_relevant_top20']}; "
        f"Hybrid/Rerank P@5 {metrics['systems']['hybrid']['broad_precision_at_5']}/{metrics['systems']['hybrid_rerank']['broad_precision_at_5']}; "
        f"rerank nDCG delta {rerank['graded_ndcg_at_5_delta']}; right-document/wrong-chunk {quality.get('right_document_wrong_chunk', 0)}."
    )


def tuning_matrix(error_analysis: dict[str, Any], overlap: dict[str, Any], rerank: dict[str, Any], quality: dict[str, Any]) -> list[dict[str, str]]:
    failure_counts = Counter(row["primary_failure"] for row in error_analysis["query_diagnostics"].values())
    return [
        item("BM25 k1/b tuning", "BM25 trails hybrid modestly on broad P@5 and nDCG.", "BM25 already has strong statute-explicit performance; no parameter sweep evidence.", "Overfit 30-query benchmark.", "MORE EVALUATION DATA NEEDED"),
        item("legal tokenizer changes", "Some lexical gaps remain in transition and procedural queries.", "Tokenizer already preserves section/statute tokens and BM25 P@5 is high.", "Could regress exact statute matching.", "MORE EVALUATION DATA NEEDED"),
        item("query expansion", "Candidate-generation gaps and ambiguous/composite queries appear.", "Expansion can add noise; current benchmark is now inspected.", "High overfitting risk.", "TARGETED TUNING JUSTIFIED"),
        item("explicit statute/section weighting", "Statute-explicit hybrid P@5 is best, suggesting section signals matter.", "Weakest cases are not only statute misses.", "May over-prioritize bare provisions over facts.", "MORE EVALUATION DATA NEEDED"),
        item("legal regime filtering/boosting", f"{failure_counts.get('legal_regime_resolution', 0)} primary legal-regime failures plus small transition subset.", "Only 3 transition-regime queries; evidence is sparse.", "Could hide useful old/new law cross references.", "TARGETED TUNING JUSTIFIED"),
        item("RRF K tuning", "Hybrid improves pooled recall@20 over BM25 and Dense.", "Hybrid P@5/nDCG gains are modest and stable; no clear RRF-specific failure dominates.", "Directly tuning on this benchmark would bias results.", "MORE EVALUATION DATA NEEDED"),
        item("dense-only changes", "Dense has strong document hit@5 and good nDCG.", "Hybrid and rerank already use dense evidence; dense model change is high blast radius.", "Model churn and cache/index rebuild cost.", "NO TUNING NEEDED"),
        item("reranker max_length", "Reranker improves graded nDCG@5.", "Broad P@5 is unchanged and harmful cases exist.", "Longer inputs increase latency and may overfit.", "MORE EVALUATION DATA NEEDED"),
        item("reranker candidate depth", "Rerank improves pooled recall@20 and strict metrics.", "Top20 is censored; depth effects cannot be isolated from frozen traces.", "More review workload and latency.", "MORE EVALUATION DATA NEEDED"),
        item("chunk-size changes", f"Right-document/wrong-chunk count is {quality['overall'].get('right_document_wrong_chunk', 0)}.", "Changing chunks invalidates the frozen benchmark and index.", "Large rebuild and comparability loss.", "MORE EVALUATION DATA NEEDED"),
        item("metadata-aware reranking", "Document/chunk mismatch and regime evidence suggest metadata could help ordering.", "Needs separate dev set and careful ablation.", "Can encode brittle shortcuts.", "TARGETED TUNING JUSTIFIED"),
    ]


def item(change: str, evidence_for: str, evidence_against: str, risk: str, recommendation: str) -> dict[str, str]:
    return {"potential_change": change, "evidence_for": evidence_for, "evidence_against": evidence_against, "risk": risk, "recommendation": recommendation}


def write_docs(error_analysis: dict[str, Any], overlap: dict[str, Any], rerank: dict[str, Any], matrix: list[dict[str, str]]) -> None:
    required = error_analysis["query_diagnostics"]
    lines = [
        "# Retrieval Error Analysis",
        "",
        "This diagnosis uses only frozen human qrels, frozen machine traces, and frozen benchmark metrics. No retrieval systems were rerun.",
        "",
        "## Overall Diagnosis",
        "",
        error_analysis["overall_diagnosis"],
        "",
        "## Candidate Generation",
        "",
        f"- broad BM25 relevant top20: {overlap['aggregate']['broad']['bm25_relevant_top20']}",
        f"- broad Dense relevant top20: {overlap['aggregate']['broad']['dense_relevant_top20']}",
        f"- broad intersection: {overlap['aggregate']['broad']['intersection']}",
        f"- broad union: {overlap['aggregate']['broad']['union']}",
        f"- broad BM25-only / Dense-only: {overlap['aggregate']['broad']['bm25_only']} / {overlap['aggregate']['broad']['dense_only']}",
        "",
        "## Reranker Findings",
        "",
        f"- helpful: {rerank['summary'].get('reranker_helpful', 0)}",
        f"- neutral: {rerank['summary'].get('reranker_neutral', 0)}",
        f"- harmful: {rerank['summary'].get('reranker_harmful', 0)}",
        "",
        "## Difficult Queries",
        "",
    ]
    for query_id in sorted(REQUIRED_QUERIES):
        row = required[query_id]
        lines.extend([f"### {query_id}", "", f"- primary failure: `{row['primary_failure']}`", f"- secondary: {', '.join(row['secondary_failures']) or 'none'}", f"- tuning could plausibly help: {row['tuning_could_plausibly_help']}", f"- evidence: {row['evidence']}", ""])
    ERROR_DOC.write_text("\n".join(lines), encoding="utf-8")
    matrix_lines = [
        "# Retrieval Tuning Decision",
        "",
        "The 30-query benchmark has now been inspected, so it must remain baseline diagnostic evidence rather than an unbiased post-tuning test set.",
        "",
        "| Potential Change | Evidence For | Evidence Against | Risk | Recommendation |",
        "|---|---|---|---|---|",
    ]
    for row in matrix:
        matrix_lines.append(f"| {row['potential_change']} | {row['evidence_for']} | {row['evidence_against']} | {row['risk']} | {row['recommendation']} |")
    matrix_lines.extend([
        "",
        "## Overfitting Safeguard",
        "",
        "Use a separate tuning/dev query set before changing retrieval parameters, or freeze a held-out subset before any tuning. Do not repeatedly tune against all 30 evaluated queries and report the same set as unbiased final performance.",
        "",
        "## Go / No-Go",
        "",
        "TARGETED RETRIEVAL TUNING JUSTIFIED: prioritize legal-regime filtering/boosting, query expansion experiments, and metadata-aware reranking on a separate development set.",
    ])
    TUNING_DOC.write_text("\n".join(matrix_lines) + "\n", encoding="utf-8")


def main() -> int:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    label_summary = json.loads(HUMAN_LABEL_SUMMARY_PATH.read_text(encoding="utf-8"))
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    per_query_metrics = json.loads(PER_QUERY_METRICS_PATH.read_text(encoding="utf-8"))
    validate_freeze(queries, judgments, label_summary, results)
    qrels, _ = build_qrels(judgments)
    overlap = overlap_analysis(queries, traces, qrels)
    rerank = rerank_analysis(per_query_metrics, traces, qrels)
    quality = chunk_quality(queries, judgments, traces)
    query_diagnostics = classify_queries(queries, qrels, overlap, rerank, per_query_metrics, quality)
    matrix = tuning_matrix({"query_diagnostics": query_diagnostics}, overlap, rerank, quality)
    error_analysis = {
        "status": "complete",
        "taxonomy": sorted(ALLOWED_FAILURES),
        "overall_diagnosis": "Most baseline weakness is localized rather than systemic: hybrid retrieval is broadly strong, reranking improves graded ordering, and remaining failures cluster around sparse transition-law/regime resolution, ambiguous composite queries, and chunk/document granularity.",
        "failure_class_counts": dict(Counter(row["primary_failure"] for row in query_diagnostics.values())),
        "query_diagnostics": query_diagnostics,
        "chunk_quality": quality,
        "tuning_decision": "TARGETED RETRIEVAL TUNING JUSTIFIED",
        "tuning_candidates": matrix,
    }
    ERROR_ANALYSIS_PATH.write_text(json.dumps(error_analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    CANDIDATE_OVERLAP_PATH.write_text(json.dumps(overlap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RERANK_DELTAS_PATH.write_text(json.dumps(rerank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_docs(error_analysis, overlap, rerank, matrix)
    print(json.dumps({"failure_class_counts": error_analysis["failure_class_counts"], "rerank_summary": rerank["summary"], "chunk_quality": quality["overall"], "decision": error_analysis["tuning_decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
