"""Evaluate conservative legal-regime-aware dev retrieval variants."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.legal_regime import regime_match_class, resolve_legal_regime
from backend.scripts.analyze_retrieval_dev_baseline import DEV_RESULTS_PATH
from backend.scripts.analyze_retrieval_eval import bootstrap_deltas, compute_metrics
from backend.scripts.build_retrieval_dev_set import DEV_JUDGMENTS_PATH, DEV_QUERIES_PATH, DEV_TRACES_PATH, DEV_VERSION

MANIFEST_DIR = DEV_RESULTS_PATH.parent
EXPERIMENT_PATH = MANIFEST_DIR / "retrieval_dev_regime_experiment.json"
PER_QUERY_PATH = MANIFEST_DIR / "retrieval_dev_regime_per_query.json"
QA_PATH = MANIFEST_DIR / "retrieval_dev_regime_resolution_qa.json"
DOC_PATH = DEV_RESULTS_PATH.parents[3] / "docs/RETRIEVAL_DEV_REGIME_EXPERIMENT.md"

VARIANTS = {
    "R0": {"adjustment": {}, "description": "Baseline Hybrid+Rerank ordering."},
    "R1": {"adjustment": {"exact_regime_match": 0.15, "transition_compatible": 0.08, "unknown_metadata": 0.0, "regime_mismatch": -0.05}, "description": "Very conservative score prior."},
    "R2": {"adjustment": {"exact_regime_match": 0.30, "transition_compatible": 0.15, "unknown_metadata": 0.0, "regime_mismatch": -0.10}, "description": "Moderate score prior."},
    "R3": {"adjustment": {"exact_regime_match": 0.20, "transition_compatible": 0.10, "unknown_metadata": 0.0, "regime_mismatch": -0.05}, "description": "Rank tie/near-tie preference via adjusted rank."},
}


def validate_dev_inputs(queries: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> None:
    if len(queries) != 20 or len(judgments) != 474:
        raise ValueError("expected frozen dev inputs")
    if any(query["development_version"] != DEV_VERSION for query in queries):
        raise ValueError("dev version changed")
    if sum(row["human_status"] == "reviewed" for row in judgments) != 474:
        raise ValueError("dev qrels are incomplete")


def regime_by_key(judgments: list[dict[str, Any]]) -> dict[tuple[str, str], str | None]:
    return {(row["query_id"], row["chunk_id"]): row.get("effective_legal_regime") for row in judgments}


def variant_traces(
    queries: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    variant: str,
    chunk_regime: dict[tuple[str, str], str | None],
) -> list[dict[str, Any]]:
    if variant == "R0":
        return [dict(row, rerank_rank=row["rerank_rank"]) for row in traces]
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    query_text = {query["query_id"]: query["query_text"] for query in queries}
    for row in traces:
        if row.get("rerank_rank") is not None:
            by_query[row["query_id"]].append(row)
    output = [dict(row) for row in traces if row.get("rerank_rank") is None]
    for query_id, rows in by_query.items():
        resolution = resolve_legal_regime(query_text[query_id])
        adjusted = []
        for row in rows:
            match = regime_match_class(resolution.regime, chunk_regime.get((query_id, row["chunk_id"])))
            if variant == "R3":
                score = -float(row["rerank_rank"]) + VARIANTS[variant]["adjustment"][match]
            else:
                score = float(row.get("rerank_score") or 0.0) + VARIANTS[variant]["adjustment"][match]
            adjusted.append((score, int(row["rerank_rank"]), row["chunk_id"], row, match))
        for rank, (_, _, _, row, match) in enumerate(sorted(adjusted, key=lambda item: (-item[0], item[1], item[2])), start=1):
            updated = dict(row)
            updated["rerank_rank"] = rank
            updated["regime_match_class"] = match
            output.append(updated)
    return sorted(output, key=lambda row: (row["query_id"], row["chunk_id"]))


def resolution_qa(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for query in queries:
        resolved = resolve_legal_regime(query["query_text"])
        rows.append(
            {
                "query_id": query["query_id"],
                "query_text": query["query_text"],
                "resolved_regime": resolved.regime,
                "confidence": resolved.confidence,
                "evidence": {
                    "explicit_codes": resolved.explicit_codes,
                    "explicit_sections": resolved.explicit_sections,
                    "detected_dates": resolved.detected_dates,
                    "transition_terms": resolved.transition_terms,
                },
            }
        )
    return rows


def by_focus(queries: list[dict[str, Any]], per_query: list[dict[str, Any]], focus: str) -> dict[str, Any]:
    ids = {query["query_id"] for query in queries if focus in query["tuning_focus"]}
    rows = [row for row in per_query if row["query_id"] in ids]
    return aggregate(rows)


def non_regime_regression(queries: list[dict[str, Any]], baseline: list[dict[str, Any]], variant: list[dict[str, Any]]) -> dict[str, Any]:
    non_regime = {query["query_id"] for query in queries if "legal_regime" not in query["tuning_focus"]}
    before = {row["query_id"]: row for row in baseline if row["query_id"] in non_regime}
    after = {row["query_id"]: row for row in variant if row["query_id"] in non_regime}
    p_deltas = []
    ndcg_deltas = []
    major = []
    for query_id in sorted(non_regime):
        p_delta = after[query_id]["systems"]["hybrid_rerank"]["broad_precision_at_5"] - before[query_id]["systems"]["hybrid_rerank"]["broad_precision_at_5"]
        n_delta = after[query_id]["systems"]["hybrid_rerank"]["graded_ndcg_at_5"] - before[query_id]["systems"]["hybrid_rerank"]["graded_ndcg_at_5"]
        p_deltas.append((query_id, p_delta))
        ndcg_deltas.append((query_id, n_delta))
        if p_delta <= -0.20 or n_delta <= -0.10:
            major.append({"query_id": query_id, "p5_delta": round(p_delta, 6), "ndcg_delta": round(n_delta, 6)})
    return {"improved": sum(delta > 0 for _, delta in p_deltas), "unchanged": sum(delta == 0 for _, delta in p_deltas), "worsened": sum(delta < 0 for _, delta in p_deltas), "mean_p5_delta": round(statistics.mean(delta for _, delta in p_deltas), 6), "mean_ndcg_delta": round(statistics.mean(delta for _, delta in ndcg_deltas), 6), "major_regressions": major}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    metrics = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_pooled_recall_at_20", "broad_mrr_at_5", "graded_ndcg_at_5", "document_hit_at_5", "strict_precision_at_5", "strict_pooled_recall_at_5", "strict_mrr_at_5", "strict_binary_ndcg_at_5"]
    return {metric: round(statistics.mean(row["systems"]["hybrid_rerank"][metric] for row in rows if row["systems"]["hybrid_rerank"][metric] is not None), 6) for metric in metrics}


def validate_baseline_reproduction(actual: dict[str, Any]) -> None:
    expected = json.loads(DEV_RESULTS_PATH.read_text(encoding="utf-8"))["overall"]["hybrid_rerank"]
    metrics = [
        "broad_precision_at_5",
        "broad_pooled_recall_at_5",
        "broad_pooled_recall_at_20",
        "broad_mrr_at_5",
        "graded_ndcg_at_5",
        "document_hit_at_5",
        "strict_precision_at_5",
        "strict_pooled_recall_at_5",
        "strict_mrr_at_5",
        "strict_binary_ndcg_at_5",
    ]
    mismatches = [metric for metric in metrics if round(float(actual[metric]), 6) != round(float(expected[metric]), 6)]
    if mismatches:
        raise ValueError(f"R0 baseline reproduction failed: {mismatches}")


def select_variant(results: dict[str, Any]) -> tuple[str, str]:
    baseline = results["variants"]["R0"]["overall"]["hybrid_rerank"]
    legal_base = results["variants"]["R0"]["legal_regime_subset"]
    candidates = []
    for variant in ["R1", "R2", "R3"]:
        row = results["variants"][variant]
        overall = row["overall"]["hybrid_rerank"]
        legal = row["legal_regime_subset"]
        regress = row["non_regime_regression"]
        legal_ndcg_delta = legal["graded_ndcg_at_5"] - legal_base["graded_ndcg_at_5"]
        legal_p5_delta = legal["broad_precision_at_5"] - legal_base["broad_precision_at_5"]
        if (
            overall["broad_precision_at_5"] >= baseline["broad_precision_at_5"]
            and legal["broad_precision_at_5"] >= legal_base["broad_precision_at_5"]
            and (legal_ndcg_delta > 0 or legal_p5_delta > 0)
            and not regress["major_regressions"]
        ):
            candidates.append((legal_ndcg_delta, overall["graded_ndcg_at_5"] - baseline["graded_ndcg_at_5"], variant))
    if not candidates:
        return "INCONCLUSIVE — RETAIN BASELINE", "No variant cleared the conservative selection criteria."
    chosen = sorted(candidates, reverse=True)[0][2]
    return f"REGIME VARIANT ACCEPTED: {chosen}", "Accepted on dev-set evidence only; promotion is not automatic."


def write_doc(payload: dict[str, Any]) -> None:
    qa_counts: dict[str, int] = defaultdict(int)
    for row in payload["resolver_qa"]:
        qa_counts[f"{row['resolved_regime']}/{row['confidence']}"] += 1
    lines = [
        "# Retrieval Development Regime-Aware Experiment",
        "",
        "This experiment uses only the dev set and does not evaluate the frozen 30-query benchmark.",
        "",
        "## Motivation",
        "",
        "D1 identified legal-regime resolution as a targeted tuning candidate for IPC/BNS and CrPC/BNSS transition failures.",
        "",
        "## Resolver Rules",
        "",
        "Explicit statute names take precedence. Mixed old/new references resolve to mixed_or_transition. The 1 July 2024 transition date is evidence but judgment year alone is not used. Bare section numbers are not mapped across statutes.",
        "",
        "## Variants",
        "",
        "| Variant | Adjustment | Description |",
        "|---|---|---|",
    ]
    for name, row in VARIANTS.items():
        lines.append(f"| {name} | `{row['adjustment']}` | {row['description']} |")
    lines.extend(
        [
            "",
            "## Dev Metrics",
            "",
            table(payload["variants"]),
            "",
            "## Strict Sensitivity",
            "",
            strict_table(payload["variants"]),
            "",
            "## Legal-Regime Subset",
            "",
            table({k: {'overall': {'hybrid_rerank': v['legal_regime_subset']}} for k, v in payload["variants"].items()}),
            "",
            "## Resolver QA Counts",
            "",
        ]
    )
    for key, count in sorted(qa_counts.items()):
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Legal-Regime Query Findings", ""])
    for query_id in [f"dev-q{index:03d}" for index in range(1, 7)]:
        baseline = next(row for row in payload["variants"]["R0"]["per_query"] if row["query_id"] == query_id)["systems"]["hybrid_rerank"]
        variant = next(row for row in payload["variants"]["R3"]["per_query"] if row["query_id"] == query_id)["systems"]["hybrid_rerank"]
        lines.append(
            f"- {query_id}: R0 P@5={baseline['broad_precision_at_5']:.3f}, nDCG@5={baseline['graded_ndcg_at_5']:.3f}; "
            f"R3 P@5={variant['broad_precision_at_5']:.3f}, nDCG@5={variant['graded_ndcg_at_5']:.3f}"
        )
    lines.extend(["", "## Non-Regime Regressions", ""])
    for name, row in payload["variants"].items():
        if name == "R0":
            continue
        lines.append(f"- {name}: improved={row['non_regime_regression']['improved']}, unchanged={row['non_regime_regression']['unchanged']}, worsened={row['non_regime_regression']['worsened']}, mean P@5 delta={row['non_regime_regression']['mean_p5_delta']}, mean nDCG delta={row['non_regime_regression']['mean_ndcg_delta']}, major regressions={len(row['non_regime_regression']['major_regressions'])}")
    lines.extend(["", "## Selection Decision", "", payload["selection_decision"], "", payload["selection_rationale"], "", "## Limitations", "", "- development-set evidence only", "- six legal-regime-focused queries", "- pooled qrels are non-exhaustive", "- no frozen benchmark evaluation was performed", "- variant is not promoted to production/default here"])
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def table(variants: dict[str, Any]) -> str:
    lines = ["| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, row in variants.items():
        m = row["overall"]["hybrid_rerank"]
        lines.append(f"| {name} | {m['broad_precision_at_5']:.3f} | {m['broad_pooled_recall_at_5']:.3f} | {m['broad_pooled_recall_at_20']:.3f} | {m['broad_mrr_at_5']:.3f} | {m['graded_ndcg_at_5']:.3f} | {m['document_hit_at_5']:.3f} |")
    return "\n".join(lines)


def strict_table(variants: dict[str, Any]) -> str:
    lines = ["| Variant | Strict P@5 | Strict R@5 | Strict MRR@5 | Strict nDCG@5 |", "|---|---:|---:|---:|---:|"]
    for name, row in variants.items():
        m = row["overall"]["hybrid_rerank"]
        lines.append(f"| {name} | {m['strict_precision_at_5']:.3f} | {m['strict_pooled_recall_at_5']:.3f} | {m['strict_mrr_at_5']:.3f} | {m['strict_binary_ndcg_at_5']:.3f} |")
    return "\n".join(lines)


def main() -> int:
    queries = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(DEV_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(DEV_TRACES_PATH.read_text(encoding="utf-8"))
    validate_dev_inputs(queries, judgments)
    chunk_regime = regime_by_key(judgments)
    variants = {}
    baseline_per_query = None
    for variant in VARIANTS:
        vt = variant_traces(queries, traces, variant, chunk_regime)
        per_query, metrics = compute_metrics(queries, judgments, vt)
        if variant == "R0":
            baseline_per_query = per_query
            validate_baseline_reproduction(metrics["overall"]["hybrid_rerank"])
        variants[variant] = {"config": VARIANTS[variant], "overall": metrics["overall"], "legal_regime_subset": by_focus(queries, per_query, "legal_regime"), "per_query": per_query}
    assert baseline_per_query is not None
    for variant in ["R1", "R2", "R3"]:
        variants[variant]["non_regime_regression"] = non_regime_regression(queries, baseline_per_query, variants[variant]["per_query"])
    variants["R0"]["non_regime_regression"] = {"improved": 0, "unchanged": 0, "worsened": 0, "mean_p5_delta": 0.0, "mean_ndcg_delta": 0.0, "major_regressions": []}
    payload = {"development_version": DEV_VERSION, "variants": variants, "resolver_qa": resolution_qa(queries)}
    payload["selection_decision"], payload["selection_rationale"] = select_variant(payload)
    payload["bootstrap"] = bootstrap_deltas(variants["R2"]["per_query"])
    EXPERIMENT_PATH.write_text(json.dumps({k: v for k, v in payload.items() if k != "variants"} | {"variants": {k: {x: y for x, y in v.items() if x != "per_query"} for k, v in variants.items()}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_QUERY_PATH.write_text(json.dumps({variant: row["per_query"] for variant, row in variants.items()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    QA_PATH.write_text(json.dumps(payload["resolver_qa"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(payload)
    print(json.dumps({"selection": payload["selection_decision"], "variants": {k: v["overall"]["hybrid_rerank"] for k, v in variants.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
