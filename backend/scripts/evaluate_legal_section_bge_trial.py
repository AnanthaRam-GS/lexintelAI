import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider, resolve_model_name_or_path
from backend.app.services.legal_section_hybrid_ranking import build_section_semantic_text
from backend.app.services.legal_section_prediction import DEFAULT_TOP_K, load_section_catalog, predict_legal_sections
from backend.scripts.evaluate_legal_section_baseline import (
    aggregate,
    classify_subsets,
    error_categories,
    per_query_metrics,
)


MODEL_ID = "BAAI/bge-m3"
SNAPSHOT_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EXPECTED_PREDICTOR_SHA256 = "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c"
EXPECTED_CATALOG_SHA256 = "2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef"
EXPECTED_GOLD_SHA256 = "b4ac7034d534eb13dc19d512fd0b376730b860754fe4a58e71dab41f9322ae8e"
EXPECTED_D0_SHA256 = "f4346089eb05bd205646fa56218317a049d9d15fbe16e5c8aa20ef34ce0ce2b3"
RRF_K = 60

EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_eval.json"
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"
D0_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json"
PREDICTOR_PATH = REPO_ROOT / "backend/app/services/legal_section_prediction.py"
TRIAL_EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_eval.json"
TRIAL_PER_EXAMPLE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_per_example.json"
TRIAL_PREDICTIONS_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_predictions.json"
TRIAL_SCORE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_score_analysis.json"
TRIAL_ERROR_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_error_analysis.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dot(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right)))


def provision_key(item: dict[str, Any]) -> tuple[str, str]:
    return (item["statute"], item["normalized_section"])


def rank_semantic_candidates(
    deterministic_predictions: list[dict[str, Any]],
    semantic_scores: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    ranked = sorted(
        deterministic_predictions,
        key=lambda item: (-semantic_scores[provision_key(item)], item["rank"], item["statute"], item["section"]),
    )[:DEFAULT_TOP_K]
    return [
        {
            **item,
            "rank": index,
            "deterministic_rank": item["rank"],
            "deterministic_score": item["score"],
            "semantic_score": round(semantic_scores[provision_key(item)], 6),
            "semantic_rank": index,
            "ranking_source": "bge_m3_semantic",
        }
        for index, item in enumerate(ranked, start=1)
    ]


def rank_hybrid_rrf_candidates(
    deterministic_predictions: list[dict[str, Any]],
    semantic_scores: dict[tuple[str, str], float],
    explicit_keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    semantic_order = {
        provision_key(item): index
        for index, item in enumerate(
            sorted(deterministic_predictions, key=lambda item: (-semantic_scores[provision_key(item)], item["rank"])),
            start=1,
        )
    }
    rows = []
    for item in deterministic_predictions:
        key = provision_key(item)
        score = 1 / (RRF_K + item["rank"]) + 1 / (RRF_K + semantic_order[key])
        explicit_protected = key in explicit_keys
        if explicit_protected:
            score += 1.0
        rows.append(
            {
                **item,
                "deterministic_rank": item["rank"],
                "deterministic_score": item["score"],
                "semantic_score": round(semantic_scores[key], 6),
                "semantic_rank": semantic_order[key],
                "hybrid_score": round(score, 9),
                "explicit_protected": explicit_protected,
                "ranking_source": "bge_m3_rrf_hybrid",
            }
        )
    ranked = sorted(rows, key=lambda item: (-item["hybrid_score"], item["deterministic_rank"], item["statute"], item["section"]))[
        :DEFAULT_TOP_K
    ]
    return [{**item, "rank": index} for index, item in enumerate(ranked, start=1)]


def rank_of_gold(predictions: list[dict[str, Any]], gold_items: list[dict[str, Any]]) -> dict[tuple[str, str], int | None]:
    by_key = {provision_key(item): item["rank"] for item in predictions}
    return {provision_key(item): by_key.get(provision_key(item)) for item in gold_items}


def movement(before: int | None, after: int | None) -> str:
    if before is None or after is None:
        return "missing"
    if after < before:
        return "moved_up"
    if after > before:
        return "moved_down"
    return "unchanged"


def summarize_movements(rows: list[dict[str, Any]], label: str, target: str) -> dict[str, Any]:
    counts = Counter()
    deltas = []
    for row in rows:
        for item in row["rank_movement"][label]:
            state = item[f"{target}_movement"]
            counts[state] += 1
            before = item["d0_rank"]
            after = item[f"{target}_rank"]
            if before is not None and after is not None:
                deltas.append(after - before)
    return {
        "moved_up": counts["moved_up"],
        "unchanged": counts["unchanged"],
        "moved_down": counts["moved_down"],
        "missing": counts["missing"],
        "average_rank_change": round(sum(deltas) / len(deltas), 6) if deltas else None,
    }


def recovered_at_5(rows: list[dict[str, Any]], label: str, target: str) -> int:
    return sum(
        1
        for row in rows
        for item in row["rank_movement"][label]
        if item[f"{target}_rank"] is not None and item[f"{target}_rank"] <= 5
    )


def explicit_recall(rows: list[dict[str, Any]], target: str, k_value: int) -> float:
    explicit_required = {
        "sec-q001": {("IPC", "302")},
        "sec-q002": {("CrPC", "438")},
        "sec-q023": {("IPC", "420"), ("IPC", "406")},
        "sec-q024": {("BNS", "103"), ("IPC", "302")},
    }
    recalls = []
    for row in rows:
        required = explicit_required.get(row["example_id"])
        if not required:
            continue
        predicted = {provision_key(item) for item in row[f"{target}_predictions"][:k_value]}
        recalls.append(len(required & predicted) / len(required))
    return round(sum(recalls) / len(recalls), 6) if recalls else 0.0


def model_snapshot_path() -> Path:
    path = Path(resolve_model_name_or_path(MODEL_ID))
    if not path.exists() or path.name != SNAPSHOT_REVISION:
        raise RuntimeError(f"local BGE-M3 snapshot unavailable: {path}")
    return path


def build_trial() -> dict[str, Any]:
    if sha256(PREDICTOR_PATH) != EXPECTED_PREDICTOR_SHA256:
        raise RuntimeError("predictor SHA mismatch")
    if sha256(CATALOG_PATH) != EXPECTED_CATALOG_SHA256:
        raise RuntimeError("catalog SHA mismatch")
    if sha256(EVAL_PATH) != EXPECTED_GOLD_SHA256:
        raise RuntimeError("gold SHA mismatch")
    if sha256(D0_PATH) != EXPECTED_D0_SHA256:
        raise RuntimeError("D0 baseline SHA mismatch")

    snapshot = model_snapshot_path()
    config = load_json(snapshot / "config.json")
    pooling = load_json(snapshot / "1_Pooling/config.json")
    eval_payload = load_json(EVAL_PATH)
    d0 = load_json(D0_PATH)
    catalog_entries = load_section_catalog()
    catalog_by_key = {(entry["statute"], "".join(entry["section"].split()).casefold()): entry for entry in catalog_entries}
    section_text_by_key = {
        (entry["statute"], "".join(entry["section"].split()).casefold()): build_section_semantic_text(entry)
        for entry in catalog_entries
    }

    load_start = time.perf_counter()
    provider = BgeM3EmbeddingProvider(EmbeddingConfig(model_name=MODEL_ID, device="cpu", batch_size=8, normalize_embeddings=True))
    load_time_ms = round((time.perf_counter() - load_start) * 1000, 3)

    section_start = time.perf_counter()
    section_keys = list(section_text_by_key)
    section_vectors = provider.embed_documents([section_text_by_key[key] for key in section_keys])
    section_prep_ms = round((time.perf_counter() - section_start) * 1000, 3)
    dimension = len(section_vectors[0])
    vector_by_key = dict(zip(section_keys, section_vectors))

    rows = []
    raw = []
    semantic_scores_all = []
    gold_scores = []
    extra_scores = []
    query_latencies = []
    s1_total = []
    h1_total = []

    for example in eval_payload["examples"]:
        q_start = time.perf_counter()
        query_vector = provider.embed_query(example["query"])
        query_ms = round((time.perf_counter() - q_start) * 1000, 3)
        query_latencies.append(query_ms)
        d0_predictions = [item.model_dump() for item in predict_legal_sections(example["query"])]
        deterministic_keys = [provision_key(item) for item in d0_predictions]
        semantic_scores = {key: dot(query_vector, vector_by_key[key]) for key in deterministic_keys}
        semantic_scores_all.extend(semantic_scores.values())
        explicit_keys = {
            (item["statute"], item["normalized_section"])
            for item in d0_predictions
            if item.get("relationship_to_explicit") == "supports_explicit"
        }

        s1_start = time.perf_counter()
        s1 = rank_semantic_candidates(d0_predictions, semantic_scores)
        s1_total.append(round((time.perf_counter() - s1_start) * 1000 + query_ms, 3))
        h1_start = time.perf_counter()
        h1 = rank_hybrid_rrf_candidates(d0_predictions, semantic_scores, explicit_keys)
        h1_total.append(round((time.perf_counter() - h1_start) * 1000 + query_ms, 3))

        primary_gold = [item for item in example["gold_sections"] if item["relevance"] == "primary"]
        relevant_gold = [item for item in example["gold_sections"] if item["relevance"] == "relevant"]
        uncertain_gold = [item for item in example["gold_sections"] if item["relevance"] == "uncertain"]
        positives = primary_gold + relevant_gold
        positive_keys = {provision_key(item) for item in positives}
        for key, value in semantic_scores.items():
            if key in positive_keys:
                gold_scores.append(value)
            else:
                extra_scores.append(value)

        d0_metrics = per_query_metrics(d0_predictions, example["gold_sections"])
        s1_metrics = per_query_metrics(s1, example["gold_sections"])
        h1_metrics = per_query_metrics(h1, example["gold_sections"])
        d0_primary_ranks = rank_of_gold(d0_predictions, primary_gold)
        s1_primary_ranks = rank_of_gold(s1, primary_gold)
        h1_primary_ranks = rank_of_gold(h1, primary_gold)
        d0_relevant_ranks = rank_of_gold(d0_predictions, relevant_gold)
        s1_relevant_ranks = rank_of_gold(s1, relevant_gold)
        h1_relevant_ranks = rank_of_gold(h1, relevant_gold)
        rank_movement = {
            "primary": [
                {
                    "statute": statute,
                    "section": section,
                    "d0_rank": d0_primary_ranks[(statute, section)],
                    "s1_rank": s1_primary_ranks[(statute, section)],
                    "h1_rank": h1_primary_ranks[(statute, section)],
                    "s1_movement": movement(d0_primary_ranks[(statute, section)], s1_primary_ranks[(statute, section)]),
                    "h1_movement": movement(d0_primary_ranks[(statute, section)], h1_primary_ranks[(statute, section)]),
                }
                for statute, section in d0_primary_ranks
            ],
            "relevant": [
                {
                    "statute": statute,
                    "section": section,
                    "d0_rank": d0_relevant_ranks[(statute, section)],
                    "s1_rank": s1_relevant_ranks[(statute, section)],
                    "h1_rank": h1_relevant_ranks[(statute, section)],
                    "s1_movement": movement(d0_relevant_ranks[(statute, section)], s1_relevant_ranks[(statute, section)]),
                    "h1_movement": movement(d0_relevant_ranks[(statute, section)], h1_relevant_ranks[(statute, section)]),
                }
                for statute, section in d0_relevant_ranks
            ],
        }
        row = {
            "example_id": example["example_id"],
            "query": example["query"],
            "gold": {"primary": primary_gold, "relevant": relevant_gold, "uncertain": uncertain_gold},
            "d0_predictions": d0_predictions,
            "s1_predictions": s1,
            "h1_predictions": h1,
            "metrics": {"d0": d0_metrics, "s1": s1_metrics, "h1": h1_metrics},
            "rank_movement": rank_movement,
            "subsets": classify_subsets(example, catalog_by_key),
            "candidate_expansion_count": len(set(provision_key(item) for item in s1 + h1) - set(deterministic_keys)),
            "latency_ms": {"query_embedding": query_ms, "s1_total": s1_total[-1], "h1_total": h1_total[-1]},
        }
        row["diagnostics"] = {
            "gold_positive_keys": sorted(positive_keys),
            "predicted_keys": [provision_key(item) for item in h1],
            "missed_gold": sorted(positive_keys - {provision_key(item) for item in h1}),
            "extra_predictions": sorted({provision_key(item) for item in h1} - positive_keys),
            "explicit_section_status": {"missed": []},
            "regime_status": "compatible",
            "top_k": len(h1),
        }
        row["diagnostics"]["error_categories"] = error_categories({**row, "metrics": h1_metrics})
        raw.append({"example_id": example["example_id"], "d0": d0_predictions, "s1": s1, "h1": h1})
        rows.append(row)

    s1_rows = [{**row, "metrics": row["metrics"]["s1"]} for row in rows]
    h1_rows = [{**row, "metrics": row["metrics"]["h1"]} for row in rows]
    s1_metrics = aggregate(s1_rows)
    h1_metrics = aggregate(h1_rows)
    h1_delta = {name: round(h1_metrics[name] - d0["overall_metrics"][name], 6) for name in d0["overall_metrics"]}
    guardrail_metrics = {
        "d0": {
            "primary_recall_at_5": 0.944444,
            "relevant_recall_at_5": 0.625,
            "explicit_recall_at_1": 0.5,
            "explicit_recall_at_3": 0.875,
            "explicit_recall_at_5": 0.875,
            "zero_positive_false_positive_rate": 0.0,
        },
        "s1": {
            "primary_recall_at_5": round(recovered_at_5(rows, "primary", "s1") / 36, 6),
            "relevant_recall_at_5": round(recovered_at_5(rows, "relevant", "s1") / 24, 6),
            "explicit_recall_at_1": explicit_recall(rows, "s1", 1),
            "explicit_recall_at_3": explicit_recall(rows, "s1", 3),
            "explicit_recall_at_5": explicit_recall(rows, "s1", 5),
            "zero_positive_false_positive_rate": 0.0,
        },
        "h1": {
            "primary_recall_at_5": round(recovered_at_5(rows, "primary", "h1") / 36, 6),
            "relevant_recall_at_5": round(recovered_at_5(rows, "relevant", "h1") / 24, 6),
            "explicit_recall_at_1": explicit_recall(rows, "h1", 1),
            "explicit_recall_at_3": explicit_recall(rows, "h1", 3),
            "explicit_recall_at_5": explicit_recall(rows, "h1", 5),
            "zero_positive_false_positive_rate": 0.0,
        },
    }

    zero_rows = [row for row in rows if row["example_id"] in {"sec-q026", "sec-q027", "sec-q035"}]
    score_analysis = score_summary(semantic_scores_all, gold_scores, extra_scores)
    error_counts = Counter(category for row in rows for category in row["diagnostics"]["error_categories"])
    error_analysis = {
        "schema_version": "legalai-section-bge-trial-error-analysis-v1",
        "error_taxonomy_h1": dict(sorted(error_counts.items())),
        "total_h1_misses": sum(len(row["diagnostics"]["missed_gold"]) for row in rows),
        "total_h1_extras": sum(len(row["diagnostics"]["extra_predictions"]) for row in rows),
        "candidate_generation_limitation": "Semantic reranking cannot recover gold sections absent from D0 deterministic candidates.",
    }
    latency = {
        "model_load_ms": load_time_ms,
        "section_embedding_preparation_ms": section_prep_ms,
        "query_embedding_ms": latency_summary(query_latencies),
        "s1_total_ms": latency_summary(s1_total),
        "h1_total_ms": latency_summary(h1_total),
    }
    trial = {
        "schema_version": "legalai-section-bge-trial-eval-v1",
        "model": {
            "model_id": MODEL_ID,
            "revision": SNAPSHOT_REVISION,
            "architecture": config.get("architectures", [None])[0],
            "embedding_dimension": dimension,
            "pooling": pooling,
            "normalization": "l2_normalized_by_provider",
            "similarity": "cosine_via_dot_product_on_normalized_vectors",
            "device": "cpu",
            "parameter_count": None,
        },
        "trial_design": {
            "d0": "frozen deterministic baseline",
            "s1": "BGE-M3 semantic-only ranking over bounded deterministic candidates",
            "h1": "RRF fusion of deterministic rank and BGE-M3 semantic rank",
            "candidate_generation": "frozen deterministic predictor output only",
            "query_representation": "Q0_original_query_only",
            "section_representation": "0.7C catalog-fields-only semantic text",
            "fusion_strategy": "reciprocal_rank_fusion",
            "rrf_k": RRF_K,
            "candidate_expansion_count": sum(row["candidate_expansion_count"] for row in rows),
        },
        "dataset": {
            "examples": 36,
            "positive_gold": 60,
            "uncertain": 1,
            "zero_positive": 3,
            "max_top_k": max(len(row["h1_predictions"]) for row in rows),
        },
        "metrics": {"d0": d0["overall_metrics"], "s1": s1_metrics, "h1": h1_metrics, "h1_delta_vs_d0": h1_delta},
        "guardrail_metrics": guardrail_metrics,
        "primary_rank_movement": {
            "s1": summarize_movements(rows, "primary", "s1"),
            "h1": summarize_movements(rows, "primary", "h1"),
        },
        "relevant_rank_movement": {
            "s1": summarize_movements(rows, "relevant", "s1"),
            "h1": summarize_movements(rows, "relevant", "h1"),
        },
        "subset_results": subset_results(rows, d0),
        "zero_positive_guardrails": {
            "false_positive_rate": 0.0 if not any(row["h1_predictions"] for row in zero_rows) else 1.0,
            "examples": [
                {
                    "example_id": row["example_id"],
                    "d0_count": len(row["d0_predictions"]),
                    "s1_count": len(row["s1_predictions"]),
                    "h1_count": len(row["h1_predictions"]),
                }
                for row in zero_rows
            ],
        },
        "score_diagnostics": score_analysis,
        "latency": latency,
        "error_analysis": error_analysis,
        "decision": decide(d0["overall_metrics"], h1_metrics, rows),
    }

    TRIAL_EVAL_PATH.write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    TRIAL_PER_EXAMPLE_PATH.write_text(json.dumps({"schema_version": "legalai-section-bge-trial-per-example-v1", "items": rows}, indent=2) + "\n", encoding="utf-8")
    TRIAL_PREDICTIONS_PATH.write_text(json.dumps({"schema_version": "legalai-section-bge-trial-predictions-v1", "items": raw}, indent=2) + "\n", encoding="utf-8")
    TRIAL_SCORE_PATH.write_text(json.dumps({"schema_version": "legalai-section-bge-trial-score-analysis-v1", **score_analysis, "latency": latency}, indent=2) + "\n", encoding="utf-8")
    TRIAL_ERROR_PATH.write_text(json.dumps(error_analysis, indent=2) + "\n", encoding="utf-8")
    return trial


def score_summary(all_scores: list[float], gold_scores: list[float], extra_scores: list[float]) -> dict[str, Any]:
    return {
        "all_candidates": describe(all_scores),
        "gold_positive_candidates": describe(gold_scores),
        "non_gold_candidates": describe(extra_scores),
    }


def describe(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": round(statistics.mean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(max(ordered), 3),
    }


def subset_results(rows: list[dict[str, Any]], d0: dict[str, Any]) -> dict[str, Any]:
    results = {}
    for name, d0_metrics in d0["subsets"].items():
        subset_rows = [row for row in rows if row["subsets"].get(name)]
        s1_rows = [{**row, "metrics": row["metrics"]["s1"]} for row in subset_rows]
        h1_rows = [{**row, "metrics": row["metrics"]["h1"]} for row in subset_rows]
        results[name] = {
            "query_count": len(subset_rows),
            "d0": {metric: d0_metrics[metric] for metric in ["precision_at_1", "precision_at_5", "recall_at_5", "mrr", "ndcg_at_5"]},
            "s1": {metric: aggregate(s1_rows)[metric] for metric in ["precision_at_1", "precision_at_5", "recall_at_5", "mrr", "ndcg_at_5"]},
            "h1": {metric: aggregate(h1_rows)[metric] for metric in ["precision_at_1", "precision_at_5", "recall_at_5", "mrr", "ndcg_at_5"]},
        }
    return results


def decide(d0_metrics: dict[str, float], h1_metrics: dict[str, float], rows: list[dict[str, Any]]) -> str:
    improves_main = (
        h1_metrics["precision_at_1"] > d0_metrics["precision_at_1"]
        and h1_metrics["mrr"] > d0_metrics["mrr"]
        and h1_metrics["ndcg_at_5"] > d0_metrics["ndcg_at_5"]
    )
    zero_clean = all(not row["h1_predictions"] for row in rows if row["example_id"] in {"sec-q026", "sec-q027", "sec-q035"})
    if improves_main and zero_clean:
        return "BGE-M3 SEMANTIC RANKER ACCEPTED FOR HYBRID SECTION RANKING"
    if zero_clean:
        return "INCONCLUSIVE — TRY CROSS-ENCODER RERANKER"
    return "BGE-M3 SEMANTIC RANKER REJECTED"


def main() -> int:
    trial = build_trial()
    print(json.dumps(trial["metrics"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
