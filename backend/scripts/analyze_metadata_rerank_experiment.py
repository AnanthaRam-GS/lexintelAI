"""Evaluate metadata-aware post-rerank variants on the retrieval dev set."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval_metadata_intent import metadata_features, parse_metadata_intent
from backend.scripts.analyze_retrieval_dev_baseline import DEV_RESULTS_PATH
from backend.scripts.analyze_retrieval_eval import compute_metrics, rankings_for_query
from backend.scripts.build_retrieval_dev_set import DEV_JUDGMENTS_PATH, DEV_QUERIES_PATH, DEV_TRACES_PATH, DEV_VERSION


MANIFEST_DIR = DEV_RESULTS_PATH.parent
EXPERIMENT_PATH = MANIFEST_DIR / "retrieval_dev_metadata_experiment.json"
PER_QUERY_PATH = MANIFEST_DIR / "retrieval_dev_metadata_per_query.json"
QA_PATH = MANIFEST_DIR / "retrieval_dev_metadata_qa.json"
FEATURE_USAGE_PATH = MANIFEST_DIR / "retrieval_dev_metadata_feature_usage.json"
DOC_PATH = DEV_RESULTS_PATH.parents[3] / "docs/RETRIEVAL_DEV_METADATA_RERANK_EXPERIMENT.md"

VARIANTS = {
    "M0": {"description": "Baseline Hybrid+Rerank ordering.", "weights": {}, "near_tie_margin": None},
    "M1": {"description": "Court/date/posture near-tie tiebreak only.", "weights": {"court_match": 0.10, "court_level_match": 0.08, "date_compatible": 0.04, "posture_match": 0.06}, "near_tie_margin": 0.15},
    "M2": {"description": "Court/date/posture/family conservative bounded prior.", "weights": {"court_match": 0.10, "court_level_match": 0.08, "date_compatible": 0.04, "posture_match": 0.06, "family_match": 0.04}, "near_tie_margin": 0.25},
    "M3": {"description": "M2 plus high-confidence regime compatibility.", "weights": {"court_match": 0.10, "court_level_match": 0.08, "date_compatible": 0.04, "posture_match": 0.06, "family_match": 0.04, "regime_match": 0.04}, "near_tie_margin": 0.25},
}
IMPORTANT_QUERIES = ["dev-q001", "dev-q003", "dev-q005", "dev-q016", "dev-q017", "dev-q018"]


def validate_dev_scope(queries: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> None:
    if len(queries) != 20 or len(judgments) != 474:
        raise ValueError("metadata experiment requires the 20-query retrieval dev set")
    if any(not query["query_id"].startswith("dev-q") or query["development_version"] != DEV_VERSION for query in queries):
        raise ValueError("non-dev query input rejected")


def metadata_by_key(judgments: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["query_id"], row["chunk_id"]): row for row in judgments}


def adjusted_traces(queries: list[dict[str, Any]], traces: list[dict[str, Any]], judgments: list[dict[str, Any]], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if variant == "M0":
        return [dict(row) for row in traces], {"feature_usage": {}, "ordering_changes": {}}
    config = VARIANTS[variant]
    metadata = metadata_by_key(judgments)
    query_text = {query["query_id"]: query["query_text"] for query in queries}
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    output = [dict(row) for row in traces if row.get("rerank_rank") is None]
    usage: Counter[str] = Counter()
    changes = {}
    for row in traces:
        if row.get("rerank_rank") is not None:
            by_query[row["query_id"]].append(row)
    for query_id, rows in by_query.items():
        intent = parse_metadata_intent(query_text[query_id])
        original = [row["chunk_id"] for row in sorted(rows, key=lambda item: (item["rerank_rank"], item["chunk_id"]))]
        ranked = []
        top_score = max(float(row.get("rerank_score") or 0.0) for row in rows)
        for row in rows:
            features = metadata_features(intent, metadata[(query_id, row["chunk_id"])])
            prior = metadata_prior(features, config["weights"])
            in_near_tie = top_score - float(row.get("rerank_score") or 0.0) <= float(config["near_tie_margin"])
            score = float(row.get("rerank_score") or 0.0) + (prior if in_near_tie else 0.0)
            for feature, state in features.items():
                usage[f"{feature}:{state}"] += 1
            ranked.append((score, int(row["rerank_rank"]), row["chunk_id"], row, features, prior, in_near_tie))
        ordered = sorted(ranked, key=lambda item: (-item[0], item[1], item[2]))
        updated_order = []
        for rank, (_, _, _, row, features, prior, in_near_tie) in enumerate(ordered, start=1):
            updated = dict(row)
            updated["rerank_rank"] = rank
            updated["metadata_features"] = features
            updated["metadata_prior"] = round(prior, 6)
            updated["metadata_near_tie_applied"] = in_near_tie
            output.append(updated)
            updated_order.append(row["chunk_id"])
        changes[query_id] = {
            "top5_order_changed": original[:5] != updated_order[:5],
            "top5_membership_changed": set(original[:5]) != set(updated_order[:5]),
            "top5_before": original[:5],
            "top5_after": updated_order[:5],
        }
    return sorted(output, key=lambda row: (row["query_id"], row["chunk_id"])), {"feature_usage": dict(sorted(usage.items())), "ordering_changes": changes}


def metadata_prior(features: dict[str, str], weights: dict[str, float]) -> float:
    total = 0.0
    for feature, weight in weights.items():
        state = features.get(feature, "neutral")
        if state == "match":
            total += weight
        elif state == "mismatch":
            total -= weight / 2
    return max(min(total, 0.20), -0.20)


def aggregate_subset(queries: list[dict[str, Any]], per_query: list[dict[str, Any]], selector: str, value: str) -> dict[str, float]:
    if selector == "query_type":
        ids = {query["query_id"] for query in queries if query["query_type"] == value}
    else:
        ids = {query["query_id"] for query in queries if value in query["tuning_focus"]}
    rows = [row["systems"]["hybrid_rerank"] for row in per_query if row["query_id"] in ids]
    metrics = ["broad_precision_at_5", "broad_pooled_recall_at_5", "broad_mrr_at_5", "graded_ndcg_at_5", "strict_precision_at_5"]
    return {metric: round(statistics.mean(row[metric] for row in rows if row[metric] is not None), 6) for metric in metrics}


def ordering_summary(baseline: list[dict[str, Any]], variant: list[dict[str, Any]], changes: dict[str, Any]) -> dict[str, Any]:
    before = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in baseline}
    after = {row["query_id"]: row["systems"]["hybrid_rerank"] for row in variant}
    p_deltas = {qid: after[qid]["broad_precision_at_5"] - before[qid]["broad_precision_at_5"] for qid in before}
    n_deltas = {qid: after[qid]["graded_ndcg_at_5"] - before[qid]["graded_ndcg_at_5"] for qid in before}
    return {
        "top5_order_changed": sum(1 for row in changes.values() if row["top5_order_changed"]),
        "top5_membership_changed": sum(1 for row in changes.values() if row["top5_membership_changed"]),
        "p5_improved": sum(delta > 0 for delta in p_deltas.values()),
        "p5_worsened": sum(delta < 0 for delta in p_deltas.values()),
        "p5_unchanged": sum(delta == 0 for delta in p_deltas.values()),
        "ndcg_improved": sum(delta > 0 for delta in n_deltas.values()),
        "ndcg_worsened": sum(delta < 0 for delta in n_deltas.values()),
        "ndcg_unchanged": sum(delta == 0 for delta in n_deltas.values()),
        "per_query": changes,
    }


def non_target_regression(queries: list[dict[str, Any]], baseline: list[dict[str, Any]], variant: list[dict[str, Any]]) -> dict[str, Any]:
    non_target = {query["query_id"] for query in queries if "metadata_reranking" not in query["tuning_focus"]}
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
        if p_delta <= -0.20 or n_delta <= -0.10:
            major.append({"query_id": query_id, "p5_delta": round(p_delta, 6), "ndcg_delta": round(n_delta, 6)})
    return {
        "improved": sum(delta > 0 for delta in p_deltas),
        "unchanged": sum(delta == 0 for delta in p_deltas),
        "worsened": sum(delta < 0 for delta in p_deltas),
        "mean_p5_delta": round(statistics.mean(p_deltas), 6),
        "mean_ndcg_delta": round(statistics.mean(n_deltas), 6),
        "major_regressions": major,
    }


def validate_baseline(metrics: dict[str, Any]) -> None:
    expected = json.loads(DEV_RESULTS_PATH.read_text(encoding="utf-8"))["overall"]["hybrid_rerank"]
    for metric in ["broad_precision_at_5", "graded_ndcg_at_5"]:
        if abs(float(metrics[metric]) - float(expected[metric])) > 0.000001:
            raise ValueError(f"M0 baseline reproduction failed for {metric}")


def qa_rows(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [intent_row(query["query_id"], query["query_text"]) for query in queries]
    for index, query in enumerate([
        "Supreme Court criminal appeal discussing murder conviction",
        "High Court petition seeking FIR quashing",
        "trial court conviction appeal involving prosecutrix testimony",
        "post July 2024 arrest procedure",
        "BNSS bail for IPC offence before July 2024",
    ], start=1):
        rows.append(intent_row(f"synthetic-{index:03d}", query))
    return rows


def intent_row(query_id: str, query: str) -> dict[str, Any]:
    intent = parse_metadata_intent(query)
    return {"query_id": query_id, "query": query, **intent.__dict__}


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
    baseline = payload["variants"]["M0"]["overall"]["hybrid_rerank"]
    target_base = payload["variants"]["M0"]["metadata_sensitive_subset"]
    candidates = []
    for variant in ["M1", "M2", "M3"]:
        row = payload["variants"][variant]
        overall = row["overall"]["hybrid_rerank"]
        target = row["metadata_sensitive_subset"]
        if overall["broad_precision_at_5"] >= baseline["broad_precision_at_5"] and target["graded_ndcg_at_5"] > target_base["graded_ndcg_at_5"] and not row["non_target_regression"]["major_regressions"]:
            candidates.append((target["graded_ndcg_at_5"] - target_base["graded_ndcg_at_5"], overall["graded_ndcg_at_5"] - baseline["graded_ndcg_at_5"], variant))
    if not candidates:
        return "INCONCLUSIVE — RETAIN BASELINE", "No metadata variant cleared the conservative dev-set selection criteria."
    chosen = sorted(candidates, reverse=True)[0][2]
    return f"METADATA VARIANT ACCEPTED: {chosen}", "Accepted on development evidence only; it is not promoted to production/default."


def important_findings(queries: list[dict[str, Any]], qa: list[dict[str, Any]], variants: dict[str, Any]) -> dict[str, Any]:
    qa_by_id = {row["query_id"]: row for row in qa}
    query_by_id = {query["query_id"]: query for query in queries}
    output = {}
    for query_id in IMPORTANT_QUERIES:
        output[query_id] = {"query": query_by_id[query_id]["query_text"], "intent": qa_by_id[query_id]}
        for variant in VARIANTS:
            row = next(item for item in variants[variant]["per_query"] if item["query_id"] == query_id)["systems"]["hybrid_rerank"]
            output[query_id][variant] = {metric: row[metric] for metric in ["broad_precision_at_5", "broad_mrr_at_5", "graded_ndcg_at_5", "strict_precision_at_5"]}
            if variant != "M0":
                output[query_id][variant]["ordering_changed"] = variants[variant]["ordering_changes"][query_id]["top5_order_changed"]
    return output


def write_doc(payload: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Development Metadata Rerank Experiment",
        "",
        "Development-set results are tuning evidence only.",
        "",
        "## Metadata Intent Parser",
        "",
        "- intents: court level/name, date period, case posture, offence family, legal regime",
        "- trusted fields: court, decision_date, case_title, bounded chunk preview, effective_offence_family, effective_legal_regime",
        "- unknown metadata is neutral",
        "- adjustment is bounded to +/-0.20 and applied only to near-tie candidates",
        "",
        "## Variants",
        "",
        "| Variant | Description |",
        "|---|---|",
    ]
    for name, row in VARIANTS.items():
        lines.append(f"| {name} | {row['description']} |")
    lines.extend(["", "## Overall Dev Results", "", metric_table(payload["variants"], "overall"), "", "## Metadata-Sensitive Results", "", metric_table(payload["variants"], "metadata_sensitive_subset"), "", "## Metadata-Reranking Focus Results", "", metric_table(payload["variants"], "metadata_reranking_subset"), "", "## Ordering Changes", ""])
    for name, row in payload["variants"].items():
        summary = row["ordering_summary"]
        lines.append(f"- {name}: order changed={summary['top5_order_changed']}, membership changed={summary['top5_membership_changed']}, P@5 improved/worsened/unchanged={summary['p5_improved']}/{summary['p5_worsened']}/{summary['p5_unchanged']}, nDCG improved/worsened/unchanged={summary['ndcg_improved']}/{summary['ndcg_worsened']}/{summary['ndcg_unchanged']}")
    lines.extend(["", "## Non-Target Regression", ""])
    for name, row in payload["variants"].items():
        regression = row["non_target_regression"]
        lines.append(f"- {name}: improved={regression['improved']}, unchanged={regression['unchanged']}, worsened={regression['worsened']}, mean P@5 delta={regression['mean_p5_delta']}, mean nDCG delta={regression['mean_ndcg_delta']}, major regressions={len(regression['major_regressions'])}")
    lines.extend(["", "## Important Query Findings", ""])
    for query_id, row in payload["important_queries"].items():
        lines.append(f"- {query_id}: court={row['intent']['court_level']}, date={row['intent']['date_relation']} {row['intent']['date_value']}, posture={row['intent']['posture']}, family={row['intent']['offence_family']}, regime={row['intent']['legal_regime']}")
    lines.extend(["", "## Bootstrap", ""])
    for metric, row in payload["bootstrap"].items():
        lines.append(f"- {metric}: mean delta={row['mean_delta']}, p05={row['p05']}, p95={row['p95']}")
    lines.extend(["", "## Selection Decision", "", payload["selection_decision"], "", payload["selection_rationale"], "", "## Feature Usage", ""])
    for key, value in payload["feature_usage"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Limitations", "", "- 20-query dev set only", "- post-rerank trace experiment over frozen dev pool", "- metadata can be sparse or title-derived", "- no production/default behavior is changed"])
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metric_table(variants: dict[str, Any], key: str) -> str:
    lines = ["| Variant | P@5 | R@5 | MRR@5 | nDCG@5 | Strict P@5 |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in variants.items():
        metrics = row[key]["hybrid_rerank"] if key == "overall" else row[key]
        lines.append(f"| {name} | {metrics['broad_precision_at_5']:.3f} | {metrics['broad_pooled_recall_at_5']:.3f} | {metrics['broad_mrr_at_5']:.3f} | {metrics['graded_ndcg_at_5']:.3f} | {metrics['strict_precision_at_5']:.3f} |")
    return "\n".join(lines)


def main() -> int:
    queries = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(DEV_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(DEV_TRACES_PATH.read_text(encoding="utf-8"))
    validate_dev_scope(queries, judgments)
    variants = {}
    feature_usage: Counter[str] = Counter()
    baseline_per_query = None
    for variant in VARIANTS:
        vt, diagnostics = adjusted_traces(queries, traces, judgments, variant)
        per_query, metrics = compute_metrics(queries, judgments, vt)
        if variant == "M0":
            validate_baseline(metrics["overall"]["hybrid_rerank"])
            baseline_per_query = per_query
        variants[variant] = {
            "config": VARIANTS[variant],
            "overall": metrics["overall"],
            "metadata_sensitive_subset": aggregate_subset(queries, per_query, "query_type", "metadata_sensitive"),
            "metadata_reranking_subset": aggregate_subset(queries, per_query, "tuning_focus", "metadata_reranking"),
            "ordering_changes": diagnostics["ordering_changes"],
            "per_query": per_query,
        }
        feature_usage.update(diagnostics["feature_usage"])
    assert baseline_per_query is not None
    for variant in VARIANTS:
        variants[variant]["ordering_summary"] = {"top5_order_changed": 0, "top5_membership_changed": 0, "p5_improved": 0, "p5_worsened": 0, "p5_unchanged": 20, "ndcg_improved": 0, "ndcg_worsened": 0, "ndcg_unchanged": 20, "per_query": {}} if variant == "M0" else ordering_summary(baseline_per_query, variants[variant]["per_query"], variants[variant]["ordering_changes"])
        variants[variant]["non_target_regression"] = {"improved": 0, "unchanged": 0, "worsened": 0, "mean_p5_delta": 0.0, "mean_ndcg_delta": 0.0, "major_regressions": []} if variant == "M0" else non_target_regression(queries, baseline_per_query, variants[variant]["per_query"])
    qa = qa_rows(queries)
    payload = {
        "development_version": DEV_VERSION,
        "query_count": len(queries),
        "judgment_count": len(judgments),
        "variants": {name: {key: value for key, value in row.items() if key != "per_query"} for name, row in variants.items()},
        "feature_usage": dict(sorted(feature_usage.items())),
        "selection_decision": "",
        "selection_rationale": "",
        "important_queries": important_findings(queries, qa, variants),
    }
    payload["selection_decision"], payload["selection_rationale"] = select_variant({"variants": variants})
    selected = payload["selection_decision"].split(": ")[-1] if payload["selection_decision"].startswith("METADATA VARIANT ACCEPTED") else "M3"
    payload["bootstrap"] = paired_bootstrap(baseline_per_query, variants[selected]["per_query"])
    EXPERIMENT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_QUERY_PATH.write_text(json.dumps({name: row["per_query"] for name, row in variants.items()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    QA_PATH.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    FEATURE_USAGE_PATH.write_text(json.dumps(payload["feature_usage"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(payload)
    print(json.dumps({"selection": payload["selection_decision"], "overall": {name: row["overall"]["hybrid_rerank"] for name, row in variants.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
