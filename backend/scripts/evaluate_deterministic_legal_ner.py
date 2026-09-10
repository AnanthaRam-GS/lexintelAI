"""Evaluate deterministic LegalAI NER against human gold labels."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.schemas.legal_ner import CanonicalEntity, NER_SCHEMA_VERSION  # noqa: E402
from backend.app.services.legal_ner import (  # noqa: E402
    CANONICAL_ENTITY_TYPES,
    DisabledLegalNERModel,
    entity_key,
    exact_entity_metrics,
    extract_deterministic_entities,
)
from backend.scripts.validate_legal_ner_eval import validate_gold_template  # noqa: E402


GOLD_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json"
BASELINE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_deterministic_baseline.json"
PER_EXAMPLE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_deterministic_per_example.json"
ERROR_ANALYSIS_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_deterministic_error_analysis.json"
DOC_PATH = REPO_ROOT / "docs/LEGAL_NER_DETERMINISTIC_BASELINE.md"
SYSTEM_NAME = "DETERMINISTIC BASELINE"
EXTRACTOR_VERSION = "deterministic_legal_ner-v1"


def load_gold_entities(example: dict[str, Any]) -> list[CanonicalEntity]:
    entities: list[CanonicalEntity] = []
    for item in example["gold_entities"]:
        entities.append(
            CanonicalEntity(
                text=item["text"],
                normalized_text=item["text"].casefold(),
                entity_type=item["entity_type"],
                start_char=item["start_char"],
                end_char=item["end_char"],
                confidence=1.0,
                source="deterministic",
                extractor="human_gold",
                model_name=None,
                provenance=[],
            )
        )
    return entities


def evaluate() -> dict[str, Any]:
    validation_errors = validate_gold_template(GOLD_PATH)
    if validation_errors:
        raise RuntimeError("gold template validation failed: " + "; ".join(validation_errors))
    if DisabledLegalNERModel().extract("Section 302 IPC") != []:
        raise RuntimeError("learned NER adapter is not disabled")
    payload = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    if payload.get("annotation_status") != "human_gold_materialized":
        raise RuntimeError("gold labels are not materialized")
    per_examples: list[dict[str, Any]] = []
    all_gold: list[CanonicalEntity] = []
    all_predictions: list[CanonicalEntity] = []
    for example in payload["examples"]:
        gold = load_gold_entities(example)
        predicted = extract_deterministic_entities(example["text"]).entities
        all_gold.extend(gold)
        all_predictions.extend(predicted)
        exact = exact_entity_metrics(predicted, gold)["overall"]
        span = span_only_metrics(predicted, gold)
        per_examples.append(
            {
                "example_id": example["example_id"],
                "text": example["text"],
                "gold_entities": [entity_to_dict(entity) for entity in gold],
                "predicted_entities": [entity_to_dict(entity) for entity in predicted],
                "true_positives": [entity_to_dict(entity) for entity in exact_matches(predicted, gold)],
                "false_positives": [entity_to_dict(entity) for entity in false_positives(predicted, gold)],
                "false_negatives": [entity_to_dict(entity) for entity in false_negatives(predicted, gold)],
                "exact_precision": exact["precision"],
                "exact_recall": exact["recall"],
                "exact_f1": exact["f1"],
                "span_only": span,
            }
        )
    global_exact = exact_entity_metrics(all_predictions, all_gold)["overall"]
    per_type = per_type_metrics(all_predictions, all_gold)
    span = span_only_metrics(all_predictions, all_gold)
    errors = analyze_errors(per_examples)
    recommendation = choose_recommendation(global_exact, per_type)
    baseline = {
        "schema_version": NER_SCHEMA_VERSION,
        "eval_version": "legalai-ner-eval-v1",
        "gold_version": payload["version"],
        "system_name": SYSTEM_NAME,
        "extractor_version": EXTRACTOR_VERSION,
        "learned_ner_enabled": False,
        "example_count": len(payload["examples"]),
        "gold_entity_count": len(all_gold),
        "prediction_count": len(all_predictions),
        "global_exact": global_exact,
        "span_only": span,
        "per_type": per_type,
        "zero_entity_examples": zero_entity_summary(per_examples),
        "recommendation": recommendation,
    }
    return {"baseline": baseline, "per_examples": per_examples, "errors": errors}


def per_type_metrics(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, dict[str, float | int]]:
    output: dict[str, dict[str, float | int]] = {}
    for entity_type in CANONICAL_ENTITY_TYPES:
        type_pred = [entity for entity in predicted if entity.entity_type == entity_type]
        type_gold = [entity for entity in gold if entity.entity_type == entity_type]
        metrics = exact_entity_metrics(type_pred, type_gold)["overall"]
        output[entity_type] = {"gold_support": len(type_gold), "predicted_count": len(type_pred), **metrics}
    return output


def span_only_metrics(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, float | int]:
    pred_keys = Counter((entity.start_char, entity.end_char) for entity in predicted)
    gold_keys = Counter((entity.start_char, entity.end_char) for entity in gold)
    tp = sum((pred_keys & gold_keys).values())
    fp = sum((pred_keys - gold_keys).values())
    fn = sum((gold_keys - pred_keys).values())
    return metric_values(tp, fp, fn)


def metric_values(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6)}


def exact_matches(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> list[CanonicalEntity]:
    gold_keys = Counter(entity_key(entity) for entity in gold)
    matches: list[CanonicalEntity] = []
    for entity in predicted:
        key = entity_key(entity)
        if gold_keys[key]:
            matches.append(entity)
            gold_keys[key] -= 1
    return matches


def false_positives(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> list[CanonicalEntity]:
    gold_keys = Counter(entity_key(entity) for entity in gold)
    output: list[CanonicalEntity] = []
    for entity in predicted:
        key = entity_key(entity)
        if gold_keys[key]:
            gold_keys[key] -= 1
        else:
            output.append(entity)
    return output


def false_negatives(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> list[CanonicalEntity]:
    pred_keys = Counter(entity_key(entity) for entity in predicted)
    output: list[CanonicalEntity] = []
    for entity in gold:
        key = entity_key(entity)
        if pred_keys[key]:
            pred_keys[key] -= 1
        else:
            output.append(entity)
    return output


def analyze_errors(per_examples: list[dict[str, Any]]) -> dict[str, Any]:
    error_type_counts: Counter[str] = Counter()
    per_type_error_counts: dict[str, Counter[str]] = defaultdict(Counter)
    false_positive_examples: list[dict[str, Any]] = []
    false_negative_examples: list[dict[str, Any]] = []
    boundary_mismatch_examples: list[dict[str, Any]] = []
    wrong_type_examples: list[dict[str, Any]] = []
    for example in per_examples:
        gold = example["gold_entities"]
        predicted = example["predicted_entities"]
        for fp in example["false_positives"]:
            category = classify_false_positive(fp, gold)
            error_type_counts[category] += 1
            per_type_error_counts[fp["entity_type"]][category] += 1
            false_positive_examples.append(error_record(example, fp, category))
            if category == "BOUNDARY_MISMATCH":
                boundary_mismatch_examples.append(error_record(example, fp, category))
            if category == "WRONG_ENTITY_TYPE":
                wrong_type_examples.append(error_record(example, fp, category))
        for fn in example["false_negatives"]:
            category = classify_false_negative(fn, predicted)
            error_type_counts[category] += 1
            per_type_error_counts[fn["entity_type"]][category] += 1
            false_negative_examples.append(error_record(example, fn, category))
            if category == "BOUNDARY_MISMATCH":
                boundary_mismatch_examples.append(error_record(example, fn, category))
            if category == "WRONG_ENTITY_TYPE":
                wrong_type_examples.append(error_record(example, fn, category))
    return {
        "total_errors": sum(error_type_counts.values()),
        "error_type_counts": dict(sorted(error_type_counts.items())),
        "per_type_error_counts": {entity_type: dict(sorted(counts.items())) for entity_type, counts in sorted(per_type_error_counts.items())},
        "false_positive_examples": false_positive_examples,
        "false_negative_examples": false_negative_examples,
        "boundary_mismatch_examples": boundary_mismatch_examples,
        "wrong_type_examples": wrong_type_examples,
    }


def classify_false_positive(prediction: dict[str, Any], gold: list[dict[str, Any]]) -> str:
    if any(prediction["start_char"] == item["start_char"] and prediction["end_char"] == item["end_char"] and prediction["entity_type"] != item["entity_type"] for item in gold):
        return "WRONG_ENTITY_TYPE"
    if any(overlaps(prediction, item) for item in gold):
        return "BOUNDARY_MISMATCH"
    return "SPURIOUS_ENTITY"


def classify_false_negative(gold: dict[str, Any], predicted: list[dict[str, Any]]) -> str:
    if any(gold["start_char"] == item["start_char"] and gold["end_char"] == item["end_char"] and gold["entity_type"] != item["entity_type"] for item in predicted):
        return "WRONG_ENTITY_TYPE"
    if any(overlaps(gold, item) for item in predicted):
        return "BOUNDARY_MISMATCH"
    return "MISSING_ENTITY_TYPE"


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left["start_char"] < right["end_char"] and right["start_char"] < left["end_char"]


def error_record(example: dict[str, Any], entity: dict[str, Any], category: str) -> dict[str, Any]:
    return {"example_id": example["example_id"], "text": example["text"], "entity": entity, "error_type": category}


def zero_entity_summary(per_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "example_id": example["example_id"],
            "gold_count": len(example["gold_entities"]),
            "prediction_count": len(example["predicted_entities"]),
            "false_positive_count": len(example["false_positives"]),
            "false_positives": example["false_positives"],
        }
        for example in per_examples
        if len(example["gold_entities"]) == 0
    ]


def choose_recommendation(global_exact: dict[str, Any], per_type: dict[str, dict[str, float | int]]) -> str:
    weak_important = [
        entity_type
        for entity_type in ("PERSON", "ORGANIZATION", "CASE_NAME", "LEGAL_ROLE", "OFFENCE", "LOCATION")
        if per_type[entity_type]["gold_support"] and float(per_type[entity_type]["recall"]) < 0.5
    ]
    if global_exact["f1"] >= 0.85 and not weak_important:
        return "DETERMINISTIC BASELINE SUFFICIENT FOR CURRENT PHASE"
    if global_exact["precision"] >= 0.8 and weak_important:
        return "HYBRID RULES + LEARNED MODEL JUSTIFIED"
    if global_exact["f1"] < 0.5:
        return "LEARNED NER MODEL JUSTIFIED"
    return "INCONCLUSIVE — MORE GOLD DATA NEEDED"


def entity_to_dict(entity: CanonicalEntity) -> dict[str, Any]:
    return {"text": entity.text, "entity_type": entity.entity_type, "start_char": entity.start_char, "end_char": entity.end_char}


def write_outputs(results: dict[str, Any]) -> None:
    BASELINE_PATH.write_text(json.dumps(results["baseline"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_EXAMPLE_PATH.write_text(json.dumps({"schema_version": NER_SCHEMA_VERSION, "system_name": SYSTEM_NAME, "examples": results["per_examples"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ERROR_ANALYSIS_PATH.write_text(json.dumps({"schema_version": NER_SCHEMA_VERSION, **results["errors"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DOC_PATH.write_text(render_doc(results), encoding="utf-8")


def render_doc(results: dict[str, Any]) -> str:
    baseline = results["baseline"]
    per_type = baseline["per_type"]
    exact = baseline["global_exact"]
    span = baseline["span_only"]
    lines = [
        "# Deterministic Legal NER Baseline",
        "",
        "## Evaluation Set",
        "",
        "36 human-reviewed examples with 89 gold entities from `legal_ner_gold_template.json`.",
        "",
        "## Evaluated System",
        "",
        "Deterministic query-analysis / legal-NER bridge only. Learned NER remains disabled.",
        "",
        "## Matching Policy",
        "",
        "Primary correctness requires exact character start, exact character end, and canonical entity type.",
        "",
        "## Overall Metrics",
        "",
        f"- TP: {exact['true_positive']}",
        f"- FP: {exact['false_positive']}",
        f"- FN: {exact['false_negative']}",
        f"- Precision: {exact['precision']}",
        f"- Recall: {exact['recall']}",
        f"- F1: {exact['f1']}",
        "",
        "## Per-Type Metrics",
        "",
        "| Type | Gold | Pred | TP | FP | FN | P | R | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for entity_type, metrics in per_type.items():
        lines.append(f"| {entity_type} | {metrics['gold_support']} | {metrics['predicted_count']} | {metrics['true_positive']} | {metrics['false_positive']} | {metrics['false_negative']} | {metrics['precision']} | {metrics['recall']} | {metrics['f1']} |")
    lines.extend(
        [
            "",
            "## Span-Only Diagnostic",
            "",
            "| TP | FP | FN | Precision | Recall | F1 |",
            "|---:|---:|---:|---:|---:|---:|",
            f"| {span['tp']} | {span['fp']} | {span['fn']} | {span['precision']} | {span['recall']} | {span['f1']} |",
            "",
            "## Zero-Entity Precision Guardrails",
            "",
        ]
    )
    for item in baseline["zero_entity_examples"]:
        lines.append(f"- `{item['example_id']}`: {item['false_positive_count']} false positives")
    lines.extend(
        [
            "",
            "## Error Analysis",
            "",
            f"Total FP/FN error records: {results['errors']['total_errors']}.",
            "",
        ]
    )
    for category, count in results["errors"]["error_type_counts"].items():
        lines.append(f"- {category}: {count}")
    strengths, gaps = strengths_and_gaps(per_type)
    lines.extend(["", "## Strengths", ""])
    lines.extend(f"- {item}" for item in strengths)
    lines.extend(["", "## Gaps", ""])
    lines.extend(f"- {item}" for item in gaps)
    lines.extend(["", "## Important Example Findings", ""])
    for finding in important_example_findings(results["per_examples"]):
        lines.append(f"- `{finding['example_id']}`: {finding['summary']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- only 36 examples",
            "- independently authored short legal queries",
            "- one human reviewer",
            "- synthetic/legal-style distribution",
            "- no judgment-document NER evaluation yet",
            "- no learned model comparison yet",
            "",
            "## Recommendation",
            "",
            baseline["recommendation"],
            "",
        ]
    )
    return "\n".join(lines)


def strengths_and_gaps(per_type: dict[str, dict[str, float | int]]) -> tuple[list[str], list[str]]:
    strengths: list[str] = []
    gaps: list[str] = []
    for entity_type, metrics in per_type.items():
        support = int(metrics["gold_support"])
        if support == 0:
            gaps.append(f"{entity_type}: no gold support in this evaluation set")
        elif float(metrics["f1"]) >= 0.8:
            strengths.append(f"{entity_type}: measured F1 {metrics['f1']} on {support} gold spans")
        elif float(metrics["f1"]) >= 0.4:
            gaps.append(f"{entity_type}: partial coverage with F1 {metrics['f1']} on {support} gold spans")
        else:
            gaps.append(f"{entity_type}: weak/no deterministic coverage with F1 {metrics['f1']} on {support} gold spans")
    return strengths, gaps


def important_example_findings(per_examples: list[dict[str, Any]]) -> list[dict[str, str]]:
    important_ids = ["ner-q001", "ner-q006", "ner-q008", "ner-q012", "ner-q016", "ner-q021", "ner-q026", "ner-q030", "ner-q033", "ner-q036"]
    by_id = {example["example_id"]: example for example in per_examples}
    findings: list[dict[str, str]] = []
    for example_id in important_ids:
        example = by_id[example_id]
        fp = len(example["false_positives"])
        fn = len(example["false_negatives"])
        if fp == 0 and fn == 0:
            summary = "all gold entities matched exactly; no false positives"
        else:
            parts = []
            if fp:
                parts.append(f"{fp} false positive(s): " + ", ".join(item["text"] for item in example["false_positives"]))
            if fn:
                parts.append(f"{fn} false negative(s): " + ", ".join(item["text"] for item in example["false_negatives"]))
            summary = "; ".join(parts)
        findings.append({"example_id": example_id, "summary": summary})
    return findings


def main() -> int:
    results = evaluate()
    write_outputs(results)
    baseline = results["baseline"]
    print(json.dumps({"examples": baseline["example_count"], "gold_entities": baseline["gold_entity_count"], "predictions": baseline["prediction_count"], "global_exact": baseline["global_exact"], "recommendation": baseline["recommendation"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
