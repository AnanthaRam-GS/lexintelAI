import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_section_prediction import (
    DEFAULT_TOP_K,
    PREDICTION_VERSION,
    predict_legal_sections,
)
from backend.app.services.query_analysis import analyze_legal_query


EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_eval.json"
SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/legal_section_gold_summary.json"
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"
PREDICTOR_PATH = REPO_ROOT / "backend/app/services/legal_section_prediction.py"
PREDICTIONS_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_predictions.json"
PER_EXAMPLE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_per_example.json"
BASELINE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json"
ERROR_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_error_analysis.json"

EXPECTED_PREDICTOR_SHA256 = "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c"
EXPECTED_CATALOG_SHA256 = "2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef"
POSITIVE_RELEVANCE = {"primary", "relevant"}
GRADE = {"primary": 2, "relevant": 1, "uncertain": 0, "not_relevant": 0}
ZERO_POSITIVE_IDS = {"sec-q026", "sec-q027", "sec-q035"}
MIXED_TRANSITION_IDS = {"sec-q024", "sec-q025", "sec-q028", "sec-q033"}
EXPLICIT_IDS = {"sec-q001", "sec-q002", "sec-q023", "sec-q024"}
EXPLICIT_REQUIRED = {
    "sec-q001": {("IPC", "302")},
    "sec-q002": {("CrPC", "438")},
    "sec-q023": {("IPC", "420"), ("IPC", "406")},
    "sec-q024": {("BNS", "103"), ("IPC", "302")},
}
PROCEDURAL_CONCEPTS = {
    "anticipatory_bail",
    "regular_bail",
    "default_bail",
    "quashing",
    "arrest_safeguards",
    "fir_registration",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def key(item: dict[str, Any]) -> tuple[str, str]:
    return (item["statute"], item["normalized_section"])


def prediction_key(item: dict[str, Any]) -> tuple[str, str]:
    return (item["statute"], item["normalized_section"])


def dcg(grades: list[int]) -> float:
    return sum(gain / math.log2(index + 1) for index, gain in enumerate(grades, start=1))


def per_query_metrics(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, Any]:
    positives = {key(item) for item in gold if item["relevance"] in POSITIVE_RELEVANCE}
    primary = {key(item) for item in gold if item["relevance"] == "primary"}
    relevant_only = {key(item) for item in gold if item["relevance"] == "relevant"}
    grades = {key(item): GRADE[item["relevance"]] for item in gold}
    ranked = [prediction_key(item) for item in predictions[:DEFAULT_TOP_K]]
    result: dict[str, Any] = {}
    for k_value in (1, 3, 5):
        top = ranked[:k_value]
        hits = sum(1 for item in top if item in positives)
        result[f"precision_at_{k_value}"] = hits / k_value
        result[f"recall_at_{k_value}"] = hits / len(positives) if positives else None
        result[f"hit_at_{k_value}"] = 1.0 if hits else 0.0
        result[f"primary_recovered_at_{k_value}"] = len(primary & set(top))
    result["relevant_recovered_at_5"] = len(relevant_only & set(ranked[:5]))
    result["reciprocal_rank"] = next((1 / index for index, item in enumerate(ranked, start=1) if item in positives), 0.0)
    observed_grades = [grades.get(item, 0) for item in ranked[:5]]
    ideal_grades = sorted([GRADE[item["relevance"]] for item in gold if item["relevance"] in POSITIVE_RELEVANCE], reverse=True)[:5]
    result["ndcg_at_5"] = dcg(observed_grades) / dcg(ideal_grades) if ideal_grades else None
    return result


def mean(values: list[float | None]) -> float:
    usable = [value for value in values if value is not None]
    return round(sum(usable) / len(usable), 6) if usable else 0.0


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "precision_at_1": mean([row["metrics"]["precision_at_1"] for row in rows]),
        "precision_at_3": mean([row["metrics"]["precision_at_3"] for row in rows]),
        "precision_at_5": mean([row["metrics"]["precision_at_5"] for row in rows]),
        "recall_at_1": mean([row["metrics"]["recall_at_1"] for row in rows]),
        "recall_at_3": mean([row["metrics"]["recall_at_3"] for row in rows]),
        "recall_at_5": mean([row["metrics"]["recall_at_5"] for row in rows]),
        "mrr": mean([row["metrics"]["reciprocal_rank"] for row in rows]),
        "ndcg_at_5": mean([row["metrics"]["ndcg_at_5"] for row in rows]),
        "hit_at_1": mean([row["metrics"]["hit_at_1"] for row in rows]),
        "hit_at_3": mean([row["metrics"]["hit_at_3"] for row in rows]),
        "hit_at_5": mean([row["metrics"]["hit_at_5"] for row in rows]),
    }


def catalog_indexes() -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, set[str]]]:
    catalog = load_json(CATALOG_PATH)["entries"]
    by_key = {(entry["statute"], normalize_section(entry["section"])): entry for entry in catalog}
    concepts_by_statute: dict[str, set[str]] = defaultdict(set)
    for entry in catalog:
        concepts_by_statute[entry["statute"]].update(entry.get("concepts", []))
    return by_key, concepts_by_statute


def normalize_section(section: str) -> str:
    return "".join(section.split()).casefold()


def classify_subsets(example: dict[str, Any], catalog_by_key: dict[tuple[str, str], dict[str, Any]]) -> dict[str, bool]:
    example_id = example["example_id"]
    positives = [item for item in example["gold_sections"] if item["relevance"] in POSITIVE_RELEVANCE]
    families = {catalog_by_key[(item["statute"], item["normalized_section"])]["offence_family"] for item in positives}
    statutes = {item["statute"] for item in positives}
    regimes = {catalog_by_key[(item["statute"], item["normalized_section"])]["regime"] for item in positives}
    return {
        "explicit": example_id in EXPLICIT_IDS,
        "plain_language": example_id not in EXPLICIT_IDS and example_id not in ZERO_POSITIVE_IDS,
        "procedural": "procedure" in families,
        "substantive": bool(families - {"procedure"}),
        "ipc_crpc": bool(statutes & {"IPC", "CrPC"}),
        "bns_bnss": bool(statutes & {"BNS", "BNSS"}),
        "special_law": "special" in regimes,
        "mixed_transition": example_id in MIXED_TRANSITION_IDS,
    }


def error_categories(row: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    gold_positive = set(row["diagnostics"]["gold_positive_keys"])
    predicted = set(row["diagnostics"]["predicted_keys"])
    missed = gold_positive - predicted
    extras = predicted - gold_positive
    if missed:
        categories.append("MISSING_GOLD_SECTION")
    if extras:
        categories.append("OVERPREDICTION")
    if row["example_id"] in ZERO_POSITIVE_IDS and predicted:
        categories.append("NEGATIVE_QUERY_FALSE_POSITIVE")
    if row["diagnostics"]["explicit_section_status"].get("missed"):
        categories.append("EXPLICIT_SECTION_MISSED")
    if row["metrics"]["primary_recovered_at_5"] < len(row["gold"]["primary"]):
        categories.append("PRIMARY_SECTION_RANKED_LOW")
    if row["metrics"]["relevant_recovered_at_5"] < len(row["gold"]["relevant"]):
        categories.append("SUPPLEMENTARY_SECTION_MISSED")
    for statute, section in missed:
        if any(statute == predicted_statute for predicted_statute, _ in predicted):
            categories.append("WRONG_SECTION")
        elif any(section == predicted_section for _predicted_statute, predicted_section in predicted):
            categories.append("WRONG_STATUTE")
    if row["diagnostics"]["regime_status"] == "mismatch":
        categories.append("REGIME_MISMATCH")
    if missed and not predicted:
        categories.append("CATALOG_CANDIDATE_NOT_TRIGGERED")
    if row["example_id"] in {"sec-q022", "sec-q033"}:
        categories.append("AMBIGUOUS_QUERY")
    return sorted(set(categories))


def build_artifacts() -> dict[str, Any]:
    predictor_sha = sha256(PREDICTOR_PATH)
    catalog_sha = sha256(CATALOG_PATH)
    if predictor_sha != EXPECTED_PREDICTOR_SHA256:
        raise RuntimeError(f"predictor SHA changed: {predictor_sha}")
    if catalog_sha != EXPECTED_CATALOG_SHA256:
        raise RuntimeError(f"catalog SHA changed: {catalog_sha}")

    eval_sha = sha256(EVAL_PATH)
    gold_summary_sha = sha256(SUMMARY_PATH)
    dataset = load_json(EVAL_PATH)
    catalog_by_key, _concepts_by_statute = catalog_indexes()
    per_example: list[dict[str, Any]] = []
    raw_predictions: list[dict[str, Any]] = []

    for example in dataset["examples"]:
        analysis = analyze_legal_query(example["query"])
        predictions = [item.model_dump() for item in predict_legal_sections(example["query"])]
        raw_predictions.append(
            {
                "example_id": example["example_id"],
                "query": example["query"],
                "explicit_sections": [item.model_dump() for item in analysis.explicit_sections],
                "predicted_sections": predictions,
            }
        )
        gold = {
            "primary": [item for item in example["gold_sections"] if item["relevance"] == "primary"],
            "relevant": [item for item in example["gold_sections"] if item["relevance"] == "relevant"],
            "uncertain": [item for item in example["gold_sections"] if item["relevance"] == "uncertain"],
        }
        metrics = per_query_metrics(predictions, example["gold_sections"])
        gold_positive = {(item["statute"], item["normalized_section"]) for item in gold["primary"] + gold["relevant"]}
        predicted_keys = [(item["statute"], item["normalized_section"]) for item in predictions]
        explicit_gold = EXPLICIT_REQUIRED.get(example["example_id"], set())
        explicit_predicted = set(predicted_keys) & explicit_gold
        predicted_regimes = {item.get("legal_regime") for item in predictions}
        gold_regimes = {
            catalog_by_key[(item["statute"], item["normalized_section"])]["regime"]
            for item in gold["primary"] + gold["relevant"]
        }
        row = {
            "example_id": example["example_id"],
            "query": example["query"],
            "gold": gold,
            "predictions": predictions,
            "metrics": metrics,
            "subsets": classify_subsets(example, catalog_by_key),
            "diagnostics": {
                "gold_positive_keys": sorted(gold_positive),
                "predicted_keys": predicted_keys,
                "missed_gold": sorted(gold_positive - set(predicted_keys)),
                "extra_predictions": sorted(set(predicted_keys) - gold_positive),
                "explicit_section_status": {
                    "required": sorted(explicit_gold),
                    "present": sorted(explicit_predicted),
                    "missed": sorted(explicit_gold - explicit_predicted),
                },
                "regime_status": "mismatch" if gold_regimes and predicted_regimes and not (gold_regimes & predicted_regimes) else "compatible",
                "top_k": len(predictions),
            },
        }
        row["diagnostics"]["error_categories"] = error_categories(row)
        per_example.append(row)

    overall = aggregate(per_example)
    by_subset = {
        name: {"query_count": len(rows), **aggregate(rows)}
        for name in [
            "plain_language",
            "procedural",
            "substantive",
            "ipc_crpc",
            "bns_bnss",
            "special_law",
            "mixed_transition",
        ]
        for rows in [[row for row in per_example if row["subsets"][name]]]
    }
    explicit_rows = [row for row in per_example if row["subsets"]["explicit"]]
    explicit_subset = {
        "query_count": len(explicit_rows),
        "recall_at_1": mean([row["metrics"]["recall_at_1"] for row in explicit_rows]),
        "recall_at_3": mean([row["metrics"]["recall_at_3"] for row in explicit_rows]),
        "recall_at_5": mean([row["metrics"]["recall_at_5"] for row in explicit_rows]),
    }

    per_statute = {}
    for statute in ["IPC", "CrPC", "BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act"]:
        gold_items = [
            (row, item)
            for row in per_example
            for item in row["gold"]["primary"] + row["gold"]["relevant"]
            if item["statute"] == statute
        ]
        retrieved = {}
        for k_value in (1, 3, 5):
            retrieved[k_value] = sum(
                1
                for row, item in gold_items
                if (item["statute"], item["normalized_section"]) in set(row["diagnostics"]["predicted_keys"][:k_value])
            )
        per_statute[statute] = {
            "gold_positive_count": len(gold_items),
            "retrieved_at_1": retrieved[1],
            "retrieved_at_3": retrieved[3],
            "retrieved_at_5": retrieved[5],
            "recall_at_5": round(retrieved[5] / len(gold_items), 6) if gold_items else 0.0,
        }

    primary_total = sum(len(row["gold"]["primary"]) for row in per_example)
    relevant_total = sum(len(row["gold"]["relevant"]) for row in per_example)
    primary_vs_relevant = {
        "primary_gold": primary_total,
        "primary_recovered_at_1": sum(row["metrics"]["primary_recovered_at_1"] for row in per_example),
        "primary_recovered_at_3": sum(row["metrics"]["primary_recovered_at_3"] for row in per_example),
        "primary_recovered_at_5": sum(row["metrics"]["primary_recovered_at_5"] for row in per_example),
        "relevant_gold": relevant_total,
        "relevant_recovered_at_5": sum(row["metrics"]["relevant_recovered_at_5"] for row in per_example),
    }
    primary_vs_relevant["primary_recall_at_5"] = round(primary_vs_relevant["primary_recovered_at_5"] / primary_total, 6)
    primary_vs_relevant["relevant_recall_at_5"] = round(primary_vs_relevant["relevant_recovered_at_5"] / relevant_total, 6)

    zero_rows = [row for row in per_example if row["example_id"] in ZERO_POSITIVE_IDS]
    zero_positive = {
        "query_count": len(zero_rows),
        "false_positive_count": sum(1 for row in zero_rows if row["predictions"]),
        "false_positive_rate": round(sum(1 for row in zero_rows if row["predictions"]) / len(zero_rows), 6),
        "clean_rate": round(sum(1 for row in zero_rows if not row["predictions"]) / len(zero_rows), 6),
        "examples": [
            {
                "example_id": row["example_id"],
                "prediction_count": len(row["predictions"]),
                "predictions": row["predictions"],
            }
            for row in zero_rows
        ],
    }
    score_distribution = {
        "confidence_counts": dict(Counter(item["confidence"] for row in per_example for item in row["predictions"])),
        "score_min": min((item["score"] for row in per_example for item in row["predictions"]), default=0.0),
        "score_max": max((item["score"] for row in per_example for item in row["predictions"]), default=0.0),
    }
    error_counts = Counter(category for row in per_example for category in row["diagnostics"]["error_categories"])
    manual_ids = [
        "sec-q001", "sec-q002", "sec-q005", "sec-q007", "sec-q009", "sec-q011", "sec-q013", "sec-q016",
        "sec-q019", "sec-q022", "sec-q023", "sec-q024", "sec-q025", "sec-q028", "sec-q029", "sec-q033",
        "sec-q034", "sec-q036",
    ]
    error_analysis = {
        "schema_version": "legalai-section-baseline-error-analysis-v1",
        "total_misses": sum(len(row["diagnostics"]["missed_gold"]) for row in per_example),
        "total_extras": sum(len(row["diagnostics"]["extra_predictions"]) for row in per_example),
        "error_category_counts": dict(sorted(error_counts.items())),
        "manual_inspection_examples": [row for row in per_example if row["example_id"] in manual_ids],
    }
    baseline = {
        "schema_version": "legalai-section-baseline-eval-v1",
        "evaluation_version": "legalai-section-baseline-phase0-v1",
        "predictor_version": PREDICTION_VERSION,
        "predictor_sha256": predictor_sha,
        "catalog_sha256": catalog_sha,
        "gold_sha256": eval_sha,
        "gold_summary_sha256": gold_summary_sha,
        "dataset": {
            "examples": len(per_example),
            "positive_gold": 60,
            "uncertain_gold": 1,
            "zero_positive_examples": sorted(ZERO_POSITIVE_IDS),
            "max_top_k": max(len(row["predictions"]) for row in per_example),
        },
        "overall_metrics": overall,
        "primary_vs_relevant_recovery": primary_vs_relevant,
        "explicit_subset": explicit_subset,
        "subsets": by_subset,
        "per_statute_results": per_statute,
        "zero_positive_guardrails": zero_positive,
        "score_confidence_diagnostics": score_distribution,
        "error_taxonomy": dict(sorted(error_counts.items())),
        "decision": "DETERMINISTIC BASELINE USEFUL BUT LEARNED MULTI-LABEL MODEL JUSTIFIED",
    }
    PREDICTIONS_PATH.write_text(json.dumps({"schema_version": "legalai-section-baseline-predictions-v1", "items": raw_predictions}, indent=2) + "\n", encoding="utf-8")
    PER_EXAMPLE_PATH.write_text(json.dumps({"schema_version": "legalai-section-baseline-per-example-v1", "items": per_example}, indent=2) + "\n", encoding="utf-8")
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    ERROR_PATH.write_text(json.dumps(error_analysis, indent=2) + "\n", encoding="utf-8")
    return baseline


def main() -> int:
    baseline = build_artifacts()
    print(json.dumps(baseline["overall_metrics"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
