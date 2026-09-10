"""Evaluate deterministic controlled query expansion on the retrieval dev set."""

from __future__ import annotations

from collections import defaultdict
import argparse
import json
from pathlib import Path
import random
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.legal_query_expansion import expanded_query_text, expansion_summary, expand_legal_query
from backend.app.services.retrieval.evaluation import TRACE_VERSION
from backend.scripts.analyze_retrieval_dev_baseline import DEV_RESULTS_PATH
from backend.scripts.analyze_retrieval_eval import SYSTEMS, compute_metrics, rankings_for_query
from backend.scripts.build_retrieval_dev_set import DEV_JUDGMENTS_PATH, DEV_QUERIES_PATH, DEV_TRACES_PATH, DEV_VERSION
from backend.scripts.build_retrieval_eval_set import RealRetriever, build_parser as eval_parser, make_service


MANIFEST_DIR = DEV_RESULTS_PATH.parent
EXPERIMENT_PATH = MANIFEST_DIR / "retrieval_dev_query_expansion_experiment.json"
PER_QUERY_PATH = MANIFEST_DIR / "retrieval_dev_query_expansion_per_query.json"
QA_PATH = MANIFEST_DIR / "retrieval_dev_query_expansion_qa.json"
OVERLAP_PATH = MANIFEST_DIR / "retrieval_dev_query_expansion_overlap.json"
DOC_PATH = DEV_RESULTS_PATH.parents[3] / "docs/RETRIEVAL_DEV_QUERY_EXPANSION_EXPERIMENT.md"

VARIANTS = {
    "Q0": "Original query only baseline reproduction.",
    "Q1": "Original query plus high-confidence expansion terms.",
    "Q2": "Original query repeated once plus bounded grouped expansion terms.",
    "Q3": "Conservative grouped expansion with hard-negative discriminator terms.",
}
IMPORTANT_QUERIES = ["dev-q006", "dev-q009", "dev-q012", "dev-q013", "dev-q014", "dev-q015", "dev-q019"]


def validate_dev_scope(queries: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> None:
    if len(queries) != 20 or len(judgments) != 474:
        raise ValueError("query expansion experiment requires the 20-query retrieval dev set")
    if any(not query["query_id"].startswith("dev-q") or query["development_version"] != DEV_VERSION for query in queries):
        raise ValueError("non-dev query input rejected")


def result_rank(results: list[Any]) -> dict[str, Any]:
    return {result.chunk_id: result for result in results}


def make_variant_traces(
    queries: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    retriever: RealRetriever,
    variant: str,
    candidate_depth: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    judged_ids = defaultdict(set)
    for row in judgments:
        judged_ids[row["query_id"]].add(row["chunk_id"])
    traces: list[dict[str, Any]] = []
    raw_rankings: dict[str, dict[str, list[str]]] = defaultdict(dict)
    judged_rankings: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for query in queries:
        query_id = query["query_id"]
        text = expanded_query_text(query["query_text"], variant)
        per_system: dict[str, dict[str, Any]] = {}
        for system, mode, rerank in [
            ("bm25", "lexical", False),
            ("dense", "dense", False),
            ("hybrid", "hybrid", False),
            ("hybrid_rerank", "hybrid", True),
        ]:
            results = retriever.retrieve(text, mode, top_k=candidate_depth, candidate_k=candidate_depth, rerank=rerank)
            raw_rankings[query_id][system] = [result.chunk_id for result in results[:20]]
            judged = [result for result in results if result.chunk_id in judged_ids[query_id]][:20]
            judged_rankings[query_id][system] = [result.chunk_id for result in judged]
            per_system[system] = result_rank(judged)
        for chunk_id in sorted(judged_ids[query_id]):
            representative = next((per_system[system][chunk_id] for system in SYSTEMS if chunk_id in per_system[system]), None)
            if representative is None:
                continue
            traces.append(trace_row(query_id, chunk_id, representative, per_system))
    return traces, {"raw_top20": raw_rankings, "judged_top20": judged_rankings}


def trace_row(query_id: str, chunk_id: str, representative: Any, systems: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def value(system: str, field: str) -> Any:
        result = systems[system].get(chunk_id)
        return getattr(result, field) if result else None

    return {
        "development_version": DEV_VERSION,
        "trace_version": TRACE_VERSION,
        "query_id": query_id,
        "chunk_id": chunk_id,
        "dense_rank": value("dense", "rank"),
        "dense_score": value("dense", "score"),
        "lexical_rank": value("bm25", "rank"),
        "lexical_score": value("bm25", "score"),
        "hybrid_rank": value("hybrid", "rank"),
        "hybrid_score": value("hybrid", "score"),
        "rerank_rank": value("hybrid_rerank", "rank"),
        "rerank_score": value("hybrid_rerank", "rerank_score"),
        "case_title": representative.case_title,
    }


def validate_baseline_reproduction(metrics: dict[str, Any]) -> None:
    expected = json.loads(DEV_RESULTS_PATH.read_text(encoding="utf-8"))["overall"]["hybrid_rerank"]
    for metric in ["broad_precision_at_5", "graded_ndcg_at_5"]:
        if abs(float(metrics[metric]) - float(expected[metric])) > 0.000001:
            raise ValueError(f"baseline reproduction differs for {metric}: {metrics[metric]} != {expected[metric]}")


def qrels_by_query(judgments: list[dict[str, Any]]) -> dict[str, dict[str, int | str]]:
    qrels: dict[str, dict[str, int | str]] = defaultdict(dict)
    for row in judgments:
        qrels[row["query_id"]][row["chunk_id"]] = row["human_relevance"]
    return qrels


def candidate_generation(ranking_source: dict[str, dict[str, list[str]]], qrels: dict[str, dict[str, int | str]]) -> dict[str, Any]:
    totals = {"bm25": 0, "dense": 0, "intersection": 0, "bm25_only": 0, "dense_only": 0, "union": 0}
    per_query = {}
    for query_id, systems in ranking_source.items():
        relevant = {chunk_id for chunk_id, grade in qrels[query_id].items() if grade in {1, 2}}
        bm25 = set(systems["bm25"][:20]) & relevant
        dense = set(systems["dense"][:20]) & relevant
        row = {
            "bm25_relevant_top20": len(bm25),
            "dense_relevant_top20": len(dense),
            "intersection": len(bm25 & dense),
            "bm25_only": len(bm25 - dense),
            "dense_only": len(dense - bm25),
            "union": len(bm25 | dense),
        }
        per_query[query_id] = row
        totals["bm25"] += row["bm25_relevant_top20"]
        totals["dense"] += row["dense_relevant_top20"]
        totals["intersection"] += row["intersection"]
        totals["bm25_only"] += row["bm25_only"]
        totals["dense_only"] += row["dense_only"]
        totals["union"] += row["union"]
    return {"aggregate": totals, "per_query": per_query}


def new_lost(variant_rankings: dict[str, dict[str, list[str]]], baseline_rankings: dict[str, dict[str, list[str]]], qrels: dict[str, dict[str, int | str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for system in ["bm25", "dense", "hybrid"]:
        new_broad = lost_broad = new_grade2 = lost_grade2 = 0
        per_query = {}
        for query_id in sorted(qrels):
            broad = {cid for cid, grade in qrels[query_id].items() if grade in {1, 2}}
            strict = {cid for cid, grade in qrels[query_id].items() if grade == 2}
            before = set(baseline_rankings[query_id][system][:20])
            after = set(variant_rankings[query_id][system][:20])
            row = {
                "new_broad": len((after - before) & broad),
                "lost_broad": len((before - after) & broad),
                "new_grade2": len((after - before) & strict),
                "lost_grade2": len((before - after) & strict),
            }
            per_query[query_id] = row
            new_broad += row["new_broad"]
            lost_broad += row["lost_broad"]
            new_grade2 += row["new_grade2"]
            lost_grade2 += row["lost_grade2"]
        output[system] = {"aggregate": {"new_broad": new_broad, "lost_broad": lost_broad, "new_grade2": new_grade2, "lost_grade2": lost_grade2}, "per_query": per_query}
    return output


def subset_metrics(queries: list[dict[str, Any]], per_query: list[dict[str, Any]], focus: str) -> dict[str, float]:
    ids = {query["query_id"] for query in queries if focus in query["tuning_focus"]}
    rows = [row["systems"]["hybrid_rerank"] for row in per_query if row["query_id"] in ids]
    metrics = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5", "graded_ndcg_at_5", "strict_precision_at_5"]
    return {metric: round(statistics.mean(row[metric] for row in rows if row[metric] is not None), 6) for metric in metrics}


def non_target_regression(queries: list[dict[str, Any]], baseline: list[dict[str, Any]], variant: list[dict[str, Any]]) -> dict[str, Any]:
    non_target = {query["query_id"] for query in queries if "query_expansion" not in query["tuning_focus"]}
    before = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in baseline}
    after = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in variant}
    p_deltas = []
    n_deltas = []
    major = []
    for query_id in sorted(non_target):
        p_delta = after[query_id]["broad_precision_at_5"] - before[query_id]["broad_precision_at_5"]
        n_delta = after[query_id]["graded_ndcg_at_5"] - before[query_id]["graded_ndcg_at_5"]
        p_deltas.append(p_delta)
        n_deltas.append(n_delta)
        if p_delta <= -0.20:
            major.append({"query_id": query_id, "p5_delta": round(p_delta, 6), "ndcg_delta": round(n_delta, 6)})
    return {
        "improved": sum(delta > 0 for delta in p_deltas),
        "unchanged": sum(delta == 0 for delta in p_deltas),
        "worsened": sum(delta < 0 for delta in p_deltas),
        "mean_p5_delta": round(statistics.mean(p_deltas), 6),
        "mean_ndcg_delta": round(statistics.mean(n_deltas), 6),
        "major_regressions": major,
    }


def qa_rows(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for query in queries:
        expansion = expand_legal_query(query["query_text"])
        rows.append(expansion_to_row(query["query_id"], expansion))
    synthetic = [
        "money was entrusted but he kept it",
        "property taken after threatening victim",
        "breach of contract",
        "breach of contract allegation wrongly framed as cheating",
        "Section 438 CrPC anticipatory bail",
    ]
    for index, text in enumerate(synthetic, start=1):
        rows.append(expansion_to_row(f"synthetic-{index:03d}", expand_legal_query(text)))
    return rows


def expansion_to_row(query_id: str, expansion: Any) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "original_query": expansion.original_query,
        "expanded_terms": expansion.expanded_terms,
        "expansion_groups": [group.__dict__ for group in expansion.expansion_groups],
        "confidence": expansion.confidence,
        "evidence": expansion.evidence,
        "warnings": expansion.warnings,
    }


def paired_bootstrap(baseline: list[dict[str, Any]], variant: list[dict[str, Any]], samples: int = 10000, seed: int = 20260908) -> dict[str, Any]:
    rng = random.Random(seed)
    before = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in baseline}
    after = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in variant}
    ids = sorted(before)
    output = {}
    for metric in ["broad_precision_at_5", "graded_ndcg_at_5", "broad_mrr_at_5"]:
        deltas = []
        for _ in range(samples):
            picked = [rng.choice(ids) for _ in ids]
            deltas.append(statistics.mean(after[qid][metric] - before[qid][metric] for qid in picked))
        output[metric] = {"mean_delta": round(statistics.mean(deltas), 6), "p05": round(sorted(deltas)[int(samples * 0.05)], 6), "p95": round(sorted(deltas)[int(samples * 0.95)], 6)}
    return output


def select_variant(payload: dict[str, Any]) -> tuple[str, str]:
    baseline = payload["variants"]["Q0"]["overall"]["hybrid_rerank"]
    target_base = payload["variants"]["Q0"]["query_expansion_subset"]
    candidates = []
    for variant in ["Q1", "Q2", "Q3"]:
        row = payload["variants"][variant]
        overall = row["overall"]["hybrid_rerank"]
        target = row["query_expansion_subset"]
        if overall["broad_precision_at_5"] >= baseline["broad_precision_at_5"] and target["graded_ndcg_at_5"] > target_base["graded_ndcg_at_5"] and not row["non_target_regression"]["major_regressions"]:
            candidates.append((target["graded_ndcg_at_5"] - target_base["graded_ndcg_at_5"], target["broad_precision_at_5"] - target_base["broad_precision_at_5"], variant))
    if not candidates:
        return "INCONCLUSIVE — RETAIN BASELINE", "No expansion variant cleared the conservative dev-set selection criteria."
    chosen = sorted(candidates, reverse=True)[0][2]
    return f"QUERY EXPANSION VARIANT ACCEPTED: {chosen}", "Accepted on development evidence only; it is not promoted to production/default."


def write_doc(payload: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Development Query Expansion Experiment",
        "",
        "This is dev-set tuning evidence, not unbiased final benchmark performance.",
        "",
        "## Expansion Engine",
        "",
        "- types: statute_alias, offence_equivalent, procedure_equivalent, plain_language_legal_mapping, transition_term, hard_negative_disambiguation",
        "- weighting: Q1 appends high-confidence terms; Q2 repeats the original query once before grouped terms; Q3 adds discriminator terms within the same expansion budget",
        "- expansion budget: 10 supplemental terms maximum",
        "- safety: no LLM rewriting, no section cross-mapping, no qrel/candidate-text leakage",
        "",
        "## Variants",
        "",
        "| Variant | Description |",
        "|---|---|",
    ]
    for name, description in VARIANTS.items():
        lines.append(f"| {name} | {description} |")
    lines.extend(["", "## Overall Dev Results", "", metric_table(payload["variants"], "overall"), "", "## Query-Expansion Focus Results", "", metric_table(payload["variants"], "query_expansion_subset"), "", "## Candidate Generation", ""])
    for name, row in payload["variants"].items():
        agg = row["candidate_generation"]["aggregate"]
        lines.append(f"- {name}: BM25={agg['bm25']}, Dense={agg['dense']}, intersection={agg['intersection']}, union={agg['union']}")
    lines.extend(["", "## Selection Decision", "", payload["selection_decision"], "", payload["selection_rationale"], "", "## Important Query Findings", ""])
    for query_id, row in payload["important_queries"].items():
        lines.append(f"- {query_id}: terms={row['expanded_terms']}; Q0 P@5/nDCG={row['Q0']['broad_precision_at_5']}/{row['Q0']['graded_ndcg_at_5']}; Q3 P@5/nDCG={row['Q3']['broad_precision_at_5']}/{row['Q3']['graded_ndcg_at_5']}")
    lines.extend(["", "## Limitations", "", "- 20-query dev set only", "- metrics are bounded by the frozen judged pool", "- new unjudged chunks are not relevance-labelled", "- no production/default retrieval behavior is changed"])
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metric_table(variants: dict[str, Any], key: str) -> str:
    lines = ["| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 | Strict P@5 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, row in variants.items():
        metrics = row[key]["hybrid_rerank"] if key == "overall" else row[key]
        lines.append(f"| {name} | {metrics['broad_precision_at_5']:.3f} | {metrics['broad_pooled_recall_at_5']:.3f} | {metrics['broad_pooled_recall_at_20']:.3f} | {metrics['broad_mrr_at_5']:.3f} | {metrics['graded_ndcg_at_5']:.3f} | {metrics.get('document_hit_at_5', 0):.3f} | {metrics['strict_precision_at_5']:.3f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    queries = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(DEV_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    validate_dev_scope(queries, judgments)
    qrels = qrels_by_query(judgments)
    retriever = RealRetriever(make_service(args))
    variants = {}
    ranking_sources = {}
    baseline_per_query = None
    baseline_rankings = None
    for variant in VARIANTS:
        if variant == "Q0":
            traces = json.loads(DEV_TRACES_PATH.read_text(encoding="utf-8"))
            ranking_source = {"judged_top20": {query["query_id"]: {system: rankings_for_query(traces, query["query_id"], system) for system in SYSTEMS} for query in queries}}
        else:
            traces, ranking_source = make_variant_traces(queries, judgments, retriever, variant, args.candidate_depth)
        per_query, metrics = compute_metrics(queries, judgments, traces)
        if variant == "Q0":
            validate_baseline_reproduction(metrics["overall"]["hybrid_rerank"])
            baseline_per_query = per_query
            baseline_rankings = ranking_source["judged_top20"]
        variants[variant] = {
            "description": VARIANTS[variant],
            "overall": metrics["overall"],
            "query_expansion_subset": subset_metrics(queries, per_query, "query_expansion"),
            "per_query": per_query,
            "candidate_generation": candidate_generation(ranking_source["judged_top20"], qrels),
        }
        ranking_sources[variant] = ranking_source["judged_top20"]
    assert baseline_per_query is not None and baseline_rankings is not None
    overlap = {}
    for variant in VARIANTS:
        variants[variant]["non_target_regression"] = {"improved": 0, "unchanged": 0, "worsened": 0, "mean_p5_delta": 0.0, "mean_ndcg_delta": 0.0, "major_regressions": []} if variant == "Q0" else non_target_regression(queries, baseline_per_query, variants[variant]["per_query"])
        overlap[variant] = {"candidate_generation": variants[variant]["candidate_generation"], "new_lost": new_lost(ranking_sources[variant], baseline_rankings, qrels)}
    qa = qa_rows(queries)
    dev_expansions = [expand_legal_query(query["query_text"]) for query in queries]
    payload = {
        "development_version": DEV_VERSION,
        "query_count": len(queries),
        "judgment_count": len(judgments),
        "variants": {name: {key: value for key, value in row.items() if key != "per_query"} for name, row in variants.items()},
        "expansion_summary": expansion_summary(dev_expansions),
        "selection_decision": "",
        "selection_rationale": "",
        "important_queries": important_findings(queries, qa, variants),
    }
    payload["selection_decision"], payload["selection_rationale"] = select_variant({"variants": variants})
    selected = payload["selection_decision"].split(": ")[-1] if payload["selection_decision"].startswith("QUERY EXPANSION VARIANT ACCEPTED") else "Q3"
    payload["bootstrap"] = paired_bootstrap(baseline_per_query, variants[selected]["per_query"])
    EXPERIMENT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_QUERY_PATH.write_text(json.dumps({name: row["per_query"] for name, row in variants.items()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    QA_PATH.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OVERLAP_PATH.write_text(json.dumps(overlap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(payload)
    print(json.dumps({"selection": payload["selection_decision"], "summary": payload["expansion_summary"], "overall": {name: row["overall"]["hybrid_rerank"] for name, row in variants.items()}}, indent=2))
    return 0


def important_findings(queries: list[dict[str, Any]], qa: list[dict[str, Any]], variants: dict[str, Any]) -> dict[str, Any]:
    qa_by_id = {row["query_id"]: row for row in qa}
    query_by_id = {query["query_id"]: query for query in queries}
    output = {}
    for query_id in IMPORTANT_QUERIES:
        output[query_id] = {
            "original_query": query_by_id[query_id]["query_text"],
            "expanded_terms": qa_by_id[query_id]["expanded_terms"],
            "high_confidence_terms": [term for group in qa_by_id[query_id]["expansion_groups"] if group["confidence"] == "high" for term in group["terms"]],
            "discriminator_terms": [term for group in qa_by_id[query_id]["expansion_groups"] if group["discriminator"] for term in group["terms"]],
        }
        for variant in VARIANTS:
            row = next(item for item in variants[variant]["per_query"] if item["query_id"] == query_id)["systems"]["hybrid_rerank"]
            output[query_id][variant] = {metric: row[metric] for metric in ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5", "graded_ndcg_at_5", "strict_precision_at_5"]}
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = eval_parser()
    parser.description = __doc__
    parser.set_defaults(candidate_depth=20, top_k=20)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
