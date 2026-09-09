"""Compare deterministic, learned-only, and hybrid LegalAI NER predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.schemas.legal_ner import CanonicalEntity, NER_SCHEMA_VERSION  # noqa: E402
from backend.app.services.hybrid_legal_ner import HybridMergeConfig, merge_hybrid_entities  # noqa: E402
from backend.app.services.legal_ner import CANONICAL_ENTITY_TYPES, exact_entity_metrics, extract_deterministic_entities  # noqa: E402
from backend.scripts.evaluate_deterministic_legal_ner import load_gold_entities, span_only_metrics  # noqa: E402
from backend.scripts.validate_legal_ner_eval import GOLD_TEMPLATE_PATH, validate_gold_template  # noqa: E402


PREDICTION_TEMPLATE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_learned_predictions_template.json"


def load_gold() -> dict[str, dict[str, Any]]:
    errors = validate_gold_template(GOLD_TEMPLATE_PATH)
    if errors:
        raise RuntimeError("gold validation failed: " + "; ".join(errors))
    payload = json.loads(GOLD_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return {example["example_id"]: example for example in payload["examples"]}


def validate_prediction_manifest(path: Path, gold_by_id: dict[str, dict[str, Any]] | None = None) -> list[str]:
    gold_by_id = gold_by_id or load_gold()
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != NER_SCHEMA_VERSION:
        errors.append("unexpected prediction schema_version")
    examples = payload.get("examples")
    if not isinstance(examples, list) or len(examples) != 36:
        errors.append("prediction manifest must contain exactly 36 examples")
        examples = []
    seen_ids: set[str] = set()
    valid_types = set(CANONICAL_ENTITY_TYPES)
    for index, example in enumerate(examples, start=1):
        example_id = example.get("example_id")
        if not isinstance(example_id, str) or not example_id:
            errors.append(f"prediction example {index} missing example_id")
            continue
        if example_id in seen_ids:
            errors.append(f"duplicate prediction example_id {example_id}")
        seen_ids.add(example_id)
        if example_id not in gold_by_id:
            errors.append(f"{example_id} not present in gold manifest")
            continue
        text = gold_by_id[example_id]["text"]
        predicted = example.get("predicted_entities")
        if not isinstance(predicted, list):
            errors.append(f"{example_id} predicted_entities must be a list")
            continue
        seen_entities: set[tuple[int, int, str]] = set()
        for entity_index, entity in enumerate(predicted, start=1):
            label = f"{example_id} prediction {entity_index}"
            entity_type = entity.get("entity_type")
            start = entity.get("start_char")
            end = entity.get("end_char")
            confidence = entity.get("confidence")
            if entity_type not in valid_types:
                errors.append(f"{label} invalid entity_type {entity_type}")
            if entity.get("source") != "model":
                errors.append(f"{label} source must be model")
            if not isinstance(start, int) or start < 0:
                errors.append(f"{label} start_char must be >= 0")
                continue
            if not isinstance(end, int) or end <= start:
                errors.append(f"{label} end_char must be greater than start_char")
                continue
            if end > len(text):
                errors.append(f"{label} end_char exceeds text length")
                continue
            if text[start:end] != entity.get("text"):
                errors.append(f"{label} text does not match exact source span")
            if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
                errors.append(f"{label} confidence must be between 0 and 1")
            key = (start, end, str(entity_type))
            if key in seen_entities:
                errors.append(f"{label} duplicates entity key {key}")
            seen_entities.add(key)
    if set(seen_ids) != set(gold_by_id):
        errors.append("prediction example IDs do not match gold manifest")
    return errors


def evaluate_prediction_manifest(path: Path, min_confidence: float = 0.7) -> dict[str, Any]:
    gold_by_id = load_gold()
    errors = validate_prediction_manifest(path, gold_by_id)
    if errors:
        raise RuntimeError("prediction validation failed: " + "; ".join(errors))
    predictions = json.loads(path.read_text(encoding="utf-8"))
    learned_by_id = {example["example_id"]: example["predicted_entities"] for example in predictions["examples"]}
    per_system = {"deterministic": [], "learned": [], "hybrid": []}
    diagnostics = []
    started = perf_counter()
    for example_id, gold_example in gold_by_id.items():
        text = gold_example["text"]
        gold = load_gold_entities(gold_example)
        deterministic = extract_deterministic_entities(text).entities
        learned = [entity_from_prediction(text, item, predictions.get("model_name") or None) for item in learned_by_id[example_id]]
        merge_started = perf_counter()
        hybrid = merge_hybrid_entities(deterministic, learned, HybridMergeConfig(min_confidence=min_confidence, mode="hybrid"))
        merge_ms = round((perf_counter() - merge_started) * 1000, 3)
        per_system["deterministic"].extend(deterministic)
        per_system["learned"].extend([entity for entity in learned if entity.confidence >= min_confidence])
        per_system["hybrid"].extend(hybrid.entities)
        diagnostics.append({"example_id": example_id, "merge_ms": merge_ms, **hybrid.diagnostics.__dict__})
    all_gold = [entity for example in gold_by_id.values() for entity in load_gold_entities(example)]
    deterministic_metrics = metrics_for(per_system["deterministic"], all_gold)
    learned_metrics = metrics_for(per_system["learned"], all_gold)
    hybrid_metrics = metrics_for(per_system["hybrid"], all_gold)
    return {
        "schema_version": NER_SCHEMA_VERSION,
        "model_name": predictions.get("model_name", ""),
        "model_version": predictions.get("model_version", ""),
        "min_confidence": min_confidence,
        "systems": {
            "deterministic": deterministic_metrics,
            "learned": learned_metrics,
            "hybrid": hybrid_metrics,
        },
        "hybrid_value": {
            "learned_only_new_tp": max(0, learned_metrics["exact"]["true_positive"] - deterministic_metrics["exact"]["true_positive"]),
            "learned_only_new_fp": learned_metrics["exact"]["false_positive"],
            "learned_filled_fn": max(0, deterministic_metrics["exact"]["false_negative"] - hybrid_metrics["exact"]["false_negative"]),
            "deterministic_protected_count": sum(item["deterministic_protected_count"] for item in diagnostics),
            "learned_suppressed_due_to_protected_overlap": sum(item["learned_suppressed_due_to_protected_overlap"] for item in diagnostics),
            "hybrid_gain_over_deterministic": {
                "delta_precision": round(hybrid_metrics["exact"]["precision"] - deterministic_metrics["exact"]["precision"], 6),
                "delta_recall": round(hybrid_metrics["exact"]["recall"] - deterministic_metrics["exact"]["recall"], 6),
                "delta_f1": round(hybrid_metrics["exact"]["f1"] - deterministic_metrics["exact"]["f1"], 6),
            },
        },
        "latency": {
            "load_time_ms": 0.0,
            "inference_ms": 0.0,
            "merge_ms": round(sum(item["merge_ms"] for item in diagnostics), 3),
            "entity_count": len(per_system["hybrid"]),
            "total_eval_ms": round((perf_counter() - started) * 1000, 3),
        },
        "merge_diagnostics": diagnostics,
    }


def metrics_for(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, Any]:
    exact = exact_entity_metrics(predicted, gold)["overall"]
    per_type = {}
    for entity_type in CANONICAL_ENTITY_TYPES:
        pred_type = [entity for entity in predicted if entity.entity_type == entity_type]
        gold_type = [entity for entity in gold if entity.entity_type == entity_type]
        per_type[entity_type] = {"gold_support": len(gold_type), "predicted_count": len(pred_type), **exact_entity_metrics(pred_type, gold_type)["overall"]}
    return {"exact": exact, "span_only": span_only_metrics(predicted, gold), "per_type": per_type}


def entity_from_prediction(text: str, item: dict[str, Any], model_name: str | None) -> CanonicalEntity:
    return CanonicalEntity(
        text=item["text"],
        normalized_text=item["text"].casefold(),
        entity_type=item["entity_type"],
        start_char=item["start_char"],
        end_char=item["end_char"],
        confidence=float(item["confidence"]),
        source="model",
        extractor="learned_prediction_manifest",
        model_name=model_name,
        provenance=[],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=PREDICTION_TEMPLATE_PATH)
    parser.add_argument("--min-confidence", type=float, default=0.7)
    args = parser.parse_args()
    result = evaluate_prediction_manifest(args.predictions, args.min_confidence)
    print(json.dumps(result["systems"]["hybrid"]["exact"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
