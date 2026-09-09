"""Run the evolawyer/inlegalbert-sc-ner-silver LegalAI NER candidate trial."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.schemas.legal_ner import CanonicalEntity, EntityProvenance, NER_SCHEMA_VERSION  # noqa: E402
from backend.app.services.hybrid_legal_ner import HybridMergeConfig, merge_hybrid_entities  # noqa: E402
from backend.app.services.legal_ner import CANONICAL_ENTITY_TYPES, exact_entity_metrics, extract_deterministic_entities  # noqa: E402
from backend.scripts.evaluate_deterministic_legal_ner import (  # noqa: E402
    classify_false_negative,
    classify_false_positive,
    false_negatives,
    false_positives,
    load_gold_entities,
    metric_values,
    span_only_metrics,
)
from backend.scripts.validate_legal_ner_eval import GOLD_TEMPLATE_PATH, validate_gold_template  # noqa: E402


MODEL_ID = "evolawyer/inlegalbert-sc-ner-silver"
PRIMARY_THRESHOLD = 0.70
DEVICE_NAME = "cpu"
TRIAL_VERSION = "legalai-inlegalbert-ner-trial-v1"

TRIAL_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_trial.json"
PER_EXAMPLE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_per_example.json"
RAW_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_raw_predictions.json"
LABEL_MAPPING_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_label_mapping.json"
ERROR_ANALYSIS_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_error_analysis.json"
LEARNED_MANIFEST_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_predictions.json"
DOC_PATH = REPO_ROOT / "docs/LEGAL_NER_INLEGALBERT_CANDIDATE_TRIAL.md"

RAW_LABEL_POLICY: dict[str, tuple[str | None, str, str]] = {
    "COURT": ("COURT", "mapped", "Court labels align directly with the LegalAI COURT type."),
    "ORG": ("ORGANIZATION", "mapped", "Organization labels map to LegalAI ORGANIZATION."),
    "ORGANIZATION": ("ORGANIZATION", "mapped", "Organization labels map to LegalAI ORGANIZATION."),
    "GPE": ("LOCATION", "mapped", "Geo-political entity labels are locations in the LegalAI schema."),
    "LOCATION": ("LOCATION", "mapped", "Location labels align directly with the LegalAI LOCATION type."),
    "DATE": ("DATE", "mapped", "Date labels align directly with the LegalAI DATE type."),
    "OTHER_PERSON": ("PERSON", "mapped", "Named or other person labels map to PERSON while preserving the observed span."),
    "PERSON": ("PERSON", "mapped", "Person labels align directly with the LegalAI PERSON type."),
    "STATUTE": ("STATUTE", "mapped", "Statute labels align directly with the LegalAI STATUTE type."),
    "PROVISION": ("SECTION", "mapped", "Provision labels are closest to LegalAI SECTION spans."),
    "CASE_CITATION": ("CASE_CITATION", "mapped", "Case-citation labels align directly with LegalAI CASE_CITATION."),
    "PETITIONER": ("PERSON", "mapped_actor", "Legal actor labels are mapped to PERSON only for the exact model-predicted span."),
    "RESPONDENT": ("PERSON", "mapped_actor", "Legal actor labels are mapped to PERSON only for the exact model-predicted span."),
    "WITNESS": ("PERSON", "mapped_actor", "Witness labels are mapped to PERSON only for the exact model-predicted span."),
    "LAWYER": ("PERSON", "mapped_actor", "Lawyer labels are mapped to PERSON only for the exact model-predicted span."),
    "JUDGE": ("PERSON", "mapped_actor", "Judge labels are mapped to PERSON only for the exact model-predicted span."),
}
MANDATORY_LIMITATIONS = [
    "silver-labelled training data",
    "not human-gold training annotations",
    "Supreme Court judgment-oriented distribution",
    "potential ORG/GPE ambiguity",
    "potential entity-boundary drift",
    "potential positional bias",
]
IMPORTANT_EXAMPLES = ["ner-q005", "ner-q008", "ner-q010", "ner-q016", "ner-q021", "ner-q025", "ner-q032", "ner-q033"]
TARGET_GAP_TYPES = ["PERSON", "ORGANIZATION", "LOCATION", "CASE_NAME"]
SHARED_TYPES = ["COURT", "DATE", "CASE_CITATION", "OFFENCE"]
PROTECTED_CHECK_TYPES = ["STATUTE", "SECTION", "LEGAL_ROLE", "POLICE_STATION", "FIR_NUMBER", "LEGAL_PROCEDURE"]


def normalized_raw_label(label: str) -> str:
    label = label.strip()
    if "-" in label:
        prefix, suffix = label.split("-", 1)
        if prefix in {"B", "I", "E", "S", "U", "L"}:
            return suffix.upper()
    return label.upper()


def canonical_label_for(raw_label: str) -> str | None:
    return RAW_LABEL_POLICY.get(normalized_raw_label(raw_label), (None, "unmapped", ""))[0]


def label_mapping_table(id2label: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for raw_label in id2label.values():
        base = normalized_raw_label(raw_label)
        if base == "O" or base in seen:
            continue
        seen.add(base)
        canonical, status, rationale = RAW_LABEL_POLICY.get(base, (None, "unmapped", "No conservative LegalAI schema mapping was defined before scoring."))
        rows.append({"raw_model_label": base, "canonical_label": canonical, "mapping_status": status, "rationale": rationale})
    return sorted(rows, key=lambda item: item["raw_model_label"])


def raw_to_canonical_entities(example_id: str, text: str, raw_predictions: list[dict[str, Any]], threshold: float = 0.0) -> tuple[list[CanonicalEntity], list[dict[str, Any]]]:
    entities: list[CanonicalEntity] = []
    unmapped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for raw in raw_predictions:
        raw_label = str(raw["raw_label"])
        canonical = canonical_label_for(raw_label)
        if canonical is None:
            unmapped.append({"example_id": example_id, **raw, "normalized_raw_label": normalized_raw_label(raw_label)})
            continue
        confidence = float(raw["confidence"])
        if confidence < threshold:
            continue
        start = int(raw["start_char"])
        end = int(raw["end_char"])
        if text[start:end] != raw["text"]:
            raise ValueError(f"{example_id} raw span text mismatch for {raw}")
        key = (start, end, canonical)
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            CanonicalEntity(
                text=raw["text"],
                normalized_text=raw["text"].casefold(),
                entity_type=canonical,
                start_char=start,
                end_char=end,
                confidence=round(confidence, 6),
                source="model",
                extractor="inlegalbert_sc_ner_silver",
                model_name=MODEL_ID,
                metadata={"raw_label": raw_label, "example_id": example_id},
                provenance=[EntityProvenance(source="model", extractor="inlegalbert_sc_ner_silver", model_name=MODEL_ID, confidence=round(confidence, 6))],
            )
        )
    return sorted(entities, key=lambda item: (item.start_char, item.end_char, str(item.entity_type))), unmapped


def entity_to_dict(entity: CanonicalEntity) -> dict[str, Any]:
    return {
        "text": entity.text,
        "entity_type": entity.entity_type,
        "start_char": entity.start_char,
        "end_char": entity.end_char,
        "confidence": entity.confidence,
        "source": entity.source,
        "extractor": entity.extractor,
        "model_name": entity.model_name,
        "metadata": entity.metadata,
    }


def load_gold_payload() -> dict[str, Any]:
    errors = validate_gold_template(GOLD_TEMPLATE_PATH)
    if errors:
        raise RuntimeError("gold validation failed: " + "; ".join(errors))
    payload = json.loads(GOLD_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if len(payload["examples"]) != 36 or sum(len(item["gold_entities"]) for item in payload["examples"]) != 89:
        raise RuntimeError("gold set does not match the frozen 36-example / 89-entity contract")
    return payload


def metrics_for(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, Any]:
    exact = exact_entity_metrics(predicted, gold)["overall"]
    per_type = {}
    for entity_type in CANONICAL_ENTITY_TYPES:
        pred_type = [entity for entity in predicted if entity.entity_type == entity_type]
        gold_type = [entity for entity in gold if entity.entity_type == entity_type]
        per_type[entity_type] = {"gold_support": len(gold_type), "predicted_count": len(pred_type), **exact_entity_metrics(pred_type, gold_type)["overall"]}
    return {"prediction_count": len(predicted), "exact": exact, "span_only": span_only_metrics(predicted, gold), "per_type": per_type}


def evaluate_from_raw(raw_payload: dict[str, Any], model_metadata: dict[str, Any], threshold: float = PRIMARY_THRESHOLD) -> dict[str, Any]:
    gold_payload = load_gold_payload()
    raw_by_id = {item["example_id"]: item["raw_predictions"] for item in raw_payload["examples"]}
    per_examples = []
    aggregate = {"gold": [], "deterministic": [], "learned": [], "hybrid": []}
    merge_diagnostics = []
    unmapped = []
    inference_latencies = [float(item["inference_ms"]) for item in raw_payload["examples"]]
    for example in gold_payload["examples"]:
        example_id = example["example_id"]
        text = example["text"]
        gold = load_gold_entities(example)
        deterministic = extract_deterministic_entities(text).entities
        learned, example_unmapped = raw_to_canonical_entities(example_id, text, raw_by_id[example_id], threshold=0.0)
        learned_primary = [entity for entity in learned if entity.confidence >= threshold]
        started = perf_counter()
        hybrid_result = merge_hybrid_entities(deterministic, learned, HybridMergeConfig(min_confidence=threshold, mode="hybrid"))
        merge_ms = round((perf_counter() - started) * 1000, 3)
        hybrid = hybrid_result.entities
        unmapped.extend(example_unmapped)
        aggregate["gold"].extend(gold)
        aggregate["deterministic"].extend(deterministic)
        aggregate["learned"].extend(learned_primary)
        aggregate["hybrid"].extend(hybrid)
        merge_diagnostics.append({"example_id": example_id, "merge_ms": merge_ms, **hybrid_result.diagnostics.__dict__})
        per_examples.append(
            {
                "example_id": example_id,
                "text": text,
                "gold_entities": [entity_to_dict(entity) for entity in gold],
                "d0_entities": [entity_to_dict(entity) for entity in deterministic],
                "l1_entities": [entity_to_dict(entity) for entity in learned_primary],
                "h1_entities": [entity_to_dict(entity) for entity in hybrid],
                "raw_model_predictions": raw_by_id[example_id],
                "raw_model_labels": sorted({item["raw_label"] for item in raw_by_id[example_id]}),
                "d0_exact": exact_entity_metrics(deterministic, gold)["overall"],
                "l1_exact": exact_entity_metrics(learned_primary, gold)["overall"],
                "h1_exact": exact_entity_metrics(hybrid, gold)["overall"],
                "l1_false_positives": [entity_to_dict(entity) for entity in false_positives(learned_primary, gold)],
                "h1_false_positives": [entity_to_dict(entity) for entity in false_positives(hybrid, gold)],
                "d0_false_negatives": [entity_to_dict(entity) for entity in false_negatives(deterministic, gold)],
                "h1_false_negatives": [entity_to_dict(entity) for entity in false_negatives(hybrid, gold)],
                "merge_diagnostics": merge_diagnostics[-1],
            }
        )
    systems = {
        "D0_deterministic": metrics_for(aggregate["deterministic"], aggregate["gold"]),
        "L1_learned": metrics_for(aggregate["learned"], aggregate["gold"]),
        "H1_hybrid": metrics_for(aggregate["hybrid"], aggregate["gold"]),
    }
    protected_regressions = protected_type_regressions(systems)
    if protected_regressions:
        raise RuntimeError(f"protected type regression detected: {protected_regressions}")
    result = {
        "schema_version": NER_SCHEMA_VERSION,
        "trial_version": TRIAL_VERSION,
        "candidate": MODEL_ID,
        "primary_threshold": threshold,
        "device": DEVICE_NAME,
        "model_metadata": model_metadata,
        "candidate_limitations_recorded_before_evaluation": MANDATORY_LIMITATIONS,
        "gold_contract": {"examples": 36, "reviewed": 36, "gold_entities": 89, "pending": 0},
        "systems": systems,
        "threshold_prediction_counts": threshold_prediction_counts(raw_payload, [0.50, 0.70, 0.90]),
        "target_gap_analysis": type_subset_metrics(systems, TARGET_GAP_TYPES),
        "shared_type_analysis": type_subset_metrics(systems, SHARED_TYPES),
        "protected_type_regression_check": {"regression_count": 0, "types": type_subset_metrics(systems, PROTECTED_CHECK_TYPES)},
        "zero_entity_guardrails": zero_entity_guardrails(per_examples),
        "important_examples": [example_summary(item) for item in per_examples if item["example_id"] in IMPORTANT_EXAMPLES],
        "new_true_positive_analysis": learned_filled_fn_analysis(per_examples),
        "new_false_positive_analysis": new_false_positive_analysis(per_examples),
        "merge_diagnostics": summarize_merge_diagnostics(merge_diagnostics),
        "boundary_analysis": boundary_analysis(per_examples),
        "error_taxonomy": {
            "L1_learned": error_taxonomy(per_examples, "l1_entities", unmapped),
            "H1_hybrid": error_taxonomy(per_examples, "h1_entities", []),
        },
        "latency": latency_summary(raw_payload["model_load_time_ms"], inference_latencies, [item["merge_ms"] for item in merge_diagnostics]),
    }
    result["decision"] = choose_decision(result)
    return {"trial": result, "per_examples": per_examples, "unmapped_predictions": unmapped}


def threshold_prediction_counts(raw_payload: dict[str, Any], thresholds: list[float]) -> dict[str, int]:
    counts = {}
    for threshold in thresholds:
        count = 0
        for example in raw_payload["examples"]:
            learned, _ = raw_to_canonical_entities(example["example_id"], example["text"], example["raw_predictions"], threshold=threshold)
            count += len(learned)
        counts[f"{threshold:.2f}"] = count
    return counts


def type_subset_metrics(systems: dict[str, Any], entity_types: list[str]) -> dict[str, Any]:
    return {system: {entity_type: payload["per_type"][entity_type] for entity_type in entity_types} for system, payload in systems.items()}


def protected_type_regressions(systems: dict[str, Any]) -> list[str]:
    regressions = []
    d0 = systems["D0_deterministic"]["per_type"]
    h1 = systems["H1_hybrid"]["per_type"]
    for entity_type in PROTECTED_CHECK_TYPES:
        if h1[entity_type]["true_positive"] < d0[entity_type]["true_positive"] or h1[entity_type]["false_positive"] > d0[entity_type]["false_positive"]:
            regressions.append(entity_type)
    return regressions


def zero_entity_guardrails(per_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "example_id": item["example_id"],
            "l1_false_positive_count": len(item["l1_false_positives"]),
            "h1_false_positive_count": len(item["h1_false_positives"]),
            "l1_false_positives": item["l1_false_positives"],
            "h1_false_positives": item["h1_false_positives"],
        }
        for item in per_examples
        if not item["gold_entities"]
    ]


def example_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "example_id": item["example_id"],
        "text": item["text"],
        "gold": item["gold_entities"],
        "D0": item["d0_entities"],
        "L1": item["l1_entities"],
        "H1": item["h1_entities"],
        "raw_model_labels": item["raw_model_labels"],
        "raw_model_predictions": item["raw_model_predictions"],
        "merge_behavior": item["merge_diagnostics"],
    }


def learned_filled_fn_analysis(per_examples: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    examples = []
    for item in per_examples:
        d0_fn = {(entity["start_char"], entity["end_char"], entity["entity_type"]): entity for entity in item["d0_false_negatives"]}
        h1_keys = {(entity["start_char"], entity["end_char"], entity["entity_type"]) for entity in item["h1_entities"]}
        for key, entity in d0_fn.items():
            if key in h1_keys:
                counts[entity["entity_type"]] += 1
                examples.append({"example_id": item["example_id"], "entity": entity})
    grouped = {entity_type: counts[entity_type] for entity_type in ["PERSON", "ORGANIZATION", "LOCATION", "COURT", "DATE", "CASE_CITATION"]}
    grouped["other"] = sum(count for entity_type, count in counts.items() if entity_type not in grouped)
    return {"learned_filled_fn": sum(counts.values()), "by_type": grouped, "examples": examples}


def new_false_positive_analysis(per_examples: list[dict[str, Any]]) -> dict[str, Any]:
    d0_fp_keys = set()
    for item in per_examples:
        for entity in false_positives([dict_to_entity(pred) for pred in item["d0_entities"]], [dict_to_entity(gold) for gold in item["gold_entities"]]):
            d0_fp_keys.add((item["example_id"], entity.start_char, entity.end_char, str(entity.entity_type)))
    learned_records = false_positive_records(per_examples, "l1_false_positives", set())
    hybrid_records = false_positive_records(per_examples, "h1_false_positives", d0_fp_keys)
    return {
        "learned_only_new_fp": len(learned_records),
        "hybrid_new_fp": len(hybrid_records),
        "learned_breakdown": breakdown_false_positives(learned_records),
        "hybrid_breakdown": breakdown_false_positives(hybrid_records),
        "learned_examples": learned_records,
        "hybrid_examples": hybrid_records,
    }


def false_positive_records(per_examples: list[dict[str, Any]], field: str, exclude: set[tuple[str, int, int, str]]) -> list[dict[str, Any]]:
    records = []
    for item in per_examples:
        for entity in item[field]:
            key = (item["example_id"], entity["start_char"], entity["end_char"], entity["entity_type"])
            if key in exclude:
                continue
            records.append({"example_id": item["example_id"], "entity": entity, "confidence_range": confidence_range(float(entity.get("confidence", 1.0)))})
    return records


def breakdown_false_positives(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter(record["entity"]["entity_type"] for record in records)
    by_range = Counter(record["confidence_range"] for record in records)
    by_example = Counter(record["example_id"] for record in records)
    return {"by_type": dict(sorted(by_type.items())), "by_confidence_range": dict(sorted(by_range.items())), "by_example": dict(sorted(by_example.items()))}


def confidence_range(confidence: float) -> str:
    if confidence < 0.7:
        return "0.50-0.69"
    if confidence < 0.9:
        return "0.70-0.89"
    return "0.90-1.00"


def summarize_merge_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    confidence = sum(int(row["learned_below_threshold"]) for row in rows)
    protected = sum(int(row["learned_suppressed_due_to_protected_overlap"]) for row in rows)
    duplicates = sum(int(row["exact_duplicates_removed"]) for row in rows)
    overlap_suppressions = sum(1 for row in rows for item in row["suppressions"] if item["reason"] == "overlap_conflict")
    other = sum(1 for row in rows for item in row["suppressions"] if item["reason"] not in {"protected_overlap", "overlap_conflict", "same_span_lower_priority"})
    overlap_conflicts = sum(int(row["overlap_conflicts"]) for row in rows)
    considered = sum(int(row["learned_input_count"]) for row in rows)
    return {
        "deterministic_protected_count": sum(int(row["deterministic_protected_count"]) for row in rows),
        "learned_candidates_considered": considered,
        "learned_accepted": considered - confidence - protected - overlap_suppressions - other,
        "learned_suppressed_by_confidence": confidence,
        "learned_suppressed_by_protected_overlap": protected,
        "learned_suppressed_by_duplicate": duplicates,
        "learned_boundary_replacements": max(0, overlap_conflicts - protected - overlap_suppressions),
        "same_span_conflicts": sum(int(row["same_span_conflicts"]) for row in rows),
        "overlap_conflicts": overlap_conflicts,
        "other_suppressions": other,
        "per_example": rows,
    }


def boundary_analysis(per_examples: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, list[dict[str, Any]]] = {entity_type: [] for entity_type in ["COURT", "DATE", "PERSON", "ORGANIZATION", "LOCATION"]}
    for item in per_examples:
        for entity_type in out:
            gold = [entity for entity in item["gold_entities"] if entity["entity_type"] == entity_type]
            for system_field in ("l1_entities", "h1_entities"):
                predictions = [entity for entity in item[system_field] if entity["entity_type"] == entity_type]
                for pred in predictions:
                    if any(pred["start_char"] == g["start_char"] and pred["end_char"] == g["end_char"] for g in gold):
                        out[entity_type].append({"example_id": item["example_id"], "system": system_field.replace("_entities", ""), "status": "exact_boundary", "entity": pred})
                    elif any(pred["start_char"] < g["end_char"] and g["start_char"] < pred["end_char"] for g in gold):
                        out[entity_type].append({"example_id": item["example_id"], "system": system_field.replace("_entities", ""), "status": "boundary_mismatch", "entity": pred})
    return out


def error_taxonomy(per_examples: list[dict[str, Any]], field: str, unmapped: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    records = []
    for item in per_examples:
        gold = item["gold_entities"]
        predicted = item[field]
        for fp in false_positives([dict_to_entity(entity) for entity in predicted], [dict_to_entity(entity) for entity in gold]):
            fp_dict = entity_to_dict(fp)
            category = classify_false_positive(fp_dict, gold)
            counts[category] += 1
            records.append({"example_id": item["example_id"], "entity": fp_dict, "error_type": category})
        for fn in false_negatives([dict_to_entity(entity) for entity in predicted], [dict_to_entity(entity) for entity in gold]):
            fn_dict = entity_to_dict(fn)
            category = classify_false_negative(fn_dict, predicted)
            counts[category] += 1
            records.append({"example_id": item["example_id"], "entity": fn_dict, "error_type": category})
    counts["UNMAPPED_MODEL_LABEL"] += len(unmapped)
    return {"error_type_counts": dict(sorted(counts.items())), "records": records, "unmapped_model_predictions": unmapped}


def dict_to_entity(item: dict[str, Any]) -> CanonicalEntity:
    return CanonicalEntity(
        text=item["text"],
        normalized_text=item["text"].casefold(),
        entity_type=item["entity_type"],
        start_char=item["start_char"],
        end_char=item["end_char"],
        confidence=float(item.get("confidence", 1.0)),
        source=item.get("source", "model"),
        extractor=item.get("extractor", "metric_fixture"),
        model_name=item.get("model_name"),
        metadata=item.get("metadata", {}),
    )


def latency_summary(load_time_ms: float, inference_ms: list[float], merge_ms: list[float]) -> dict[str, Any]:
    return {
        "model_load_time_ms": round(load_time_ms, 3),
        "mean_inference_ms": round(statistics.mean(inference_ms), 3) if inference_ms else 0.0,
        "median_inference_ms": round(statistics.median(inference_ms), 3) if inference_ms else 0.0,
        "p95_inference_ms": round(sorted(inference_ms)[int(0.95 * (len(inference_ms) - 1))], 3) if inference_ms else 0.0,
        "max_inference_ms": round(max(inference_ms), 3) if inference_ms else 0.0,
        "total_inference_ms": round(sum(inference_ms), 3),
        "mean_merge_ms": round(statistics.mean(merge_ms), 3) if merge_ms else 0.0,
    }


def choose_decision(result: dict[str, Any]) -> str:
    d0 = result["systems"]["D0_deterministic"]["exact"]
    h1 = result["systems"]["H1_hybrid"]["exact"]
    useful_target = any(result["systems"]["H1_hybrid"]["per_type"][entity_type]["true_positive"] > result["systems"]["D0_deterministic"]["per_type"][entity_type]["true_positive"] for entity_type in ["PERSON", "ORGANIZATION", "LOCATION"])
    zero_fp = sum(item["h1_false_positive_count"] for item in result["zero_entity_guardrails"]) == 0
    if h1["f1"] > d0["f1"] and h1["recall"] > d0["recall"] and h1["precision"] >= d0["precision"] - 0.02 and useful_target and zero_fp:
        return "LEARNED CANDIDATE ACCEPTED FOR HYBRID NER"
    if h1["f1"] <= d0["f1"] or h1["precision"] < d0["precision"] - 0.05:
        return "LEARNED CANDIDATE REJECTED"
    return "INCONCLUSIVE - TRY SECOND CANDIDATE"


def run_model(gold_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from huggingface_hub import model_info, snapshot_download
    from transformers import AutoConfig, AutoModelForTokenClassification, AutoTokenizer, pipeline
    import torch

    info = model_info(MODEL_ID)
    snapshot_path = Path(snapshot_download(repo_id=MODEL_ID, allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "*.bin", "vocab*"]))
    started = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    config = AutoConfig.from_pretrained(MODEL_ID)
    model = AutoModelForTokenClassification.from_pretrained(MODEL_ID)
    model_load_time_ms = round((perf_counter() - started) * 1000, 3)
    model.eval()
    ner = pipeline("token-classification", model=model, tokenizer=tokenizer, aggregation_strategy="simple", device=-1)
    examples = []
    for example in gold_payload["examples"]:
        started = perf_counter()
        predictions = ner(example["text"])
        inference_ms = round((perf_counter() - started) * 1000, 3)
        examples.append(
            {
                "example_id": example["example_id"],
                "text": example["text"],
                "inference_ms": inference_ms,
                "raw_predictions": [pipeline_prediction_to_raw(example["example_id"], example["text"], item) for item in predictions],
            }
        )
    id2label = {str(key): value for key, value in config.id2label.items()}
    metadata = {
        "model_id": MODEL_ID,
        "revision": info.sha,
        "config_architectures": config.architectures,
        "id2label": id2label,
        "label2id": {str(key): int(value) for key, value in config.label2id.items()},
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "tokenizer_class": tokenizer.__class__.__name__,
        "local_cache_identifier": f"huggingface_hub/{snapshot_path.parent.name}/snapshots/{snapshot_path.name}",
        "license": getattr(info, "card_data", None).license if getattr(info, "card_data", None) else None,
        "environment": {"torch": torch.__version__},
    }
    raw_payload = {"schema_version": NER_SCHEMA_VERSION, "candidate": MODEL_ID, "model_metadata": metadata, "model_load_time_ms": model_load_time_ms, "examples": examples}
    return raw_payload, metadata, label_mapping_table(id2label)


def pipeline_prediction_to_raw(example_id: str, text: str, item: dict[str, Any]) -> dict[str, Any]:
    raw_label = str(item.get("entity_group") or item.get("entity") or "")
    start = int(item["start"])
    end = int(item["end"])
    return {
        "example_id": example_id,
        "text": text[start:end],
        "model_text": str(item["word"]),
        "start_char": start,
        "end_char": end,
        "raw_label": raw_label,
        "confidence": round(float(item["score"]), 6),
    }


def write_outputs(evaluation: dict[str, Any], raw_payload: dict[str, Any], label_mapping: list[dict[str, Any]]) -> None:
    trial = evaluation["trial"]
    TRIAL_PATH.write_text(json.dumps(trial, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PER_EXAMPLE_PATH.write_text(json.dumps({"schema_version": NER_SCHEMA_VERSION, "candidate": MODEL_ID, "examples": evaluation["per_examples"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RAW_PATH.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LABEL_MAPPING_PATH.write_text(json.dumps({"schema_version": NER_SCHEMA_VERSION, "candidate": MODEL_ID, "mapping_policy": label_mapping}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ERROR_ANALYSIS_PATH.write_text(json.dumps({"schema_version": NER_SCHEMA_VERSION, "candidate": MODEL_ID, **trial["error_taxonomy"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LEARNED_MANIFEST_PATH.write_text(json.dumps(render_prediction_manifest(evaluation["per_examples"], trial), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DOC_PATH.write_text(render_doc(trial), encoding="utf-8")


def render_prediction_manifest(per_examples: list[dict[str, Any]], trial: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": NER_SCHEMA_VERSION,
        "model_name": MODEL_ID,
        "model_version": trial["model_metadata"].get("revision"),
        "prediction_status": "candidate_trial_only",
        "primary_threshold": trial["primary_threshold"],
        "examples": [{"example_id": item["example_id"], "predicted_entities": item["l1_entities"]} for item in per_examples],
    }


def render_doc(trial: dict[str, Any]) -> str:
    d0 = trial["systems"]["D0_deterministic"]["exact"]
    l1 = trial["systems"]["L1_learned"]["exact"]
    h1 = trial["systems"]["H1_hybrid"]["exact"]
    span = trial["systems"]
    lines = [
        "# InLegalBERT Silver Candidate NER Trial",
        "",
        f"Candidate: `{MODEL_ID}`.",
        "",
        f"Decision: **{trial['decision']}**.",
        "",
        "## Candidate Identity",
        "",
        f"- Revision: `{trial['model_metadata'].get('revision')}`",
        f"- Architecture: `{trial['model_metadata'].get('config_architectures')}`",
        f"- Tokenizer: `{trial['model_metadata'].get('tokenizer_class')}`",
        f"- Parameters: {trial['model_metadata'].get('parameter_count')}",
        f"- License metadata: `{trial['model_metadata'].get('license')}`",
        f"- Local cache identifier: `{trial['model_metadata'].get('local_cache_identifier')}`",
        "",
        "## Primary Metrics",
        "",
        "| Metric | D0 Deterministic | L1 Learned | H1 Hybrid |",
        "|---|---:|---:|---:|",
        f"| Prediction count | {trial['systems']['D0_deterministic']['prediction_count']} | {trial['systems']['L1_learned']['prediction_count']} | {trial['systems']['H1_hybrid']['prediction_count']} |",
        f"| TP | {d0['true_positive']} | {l1['true_positive']} | {h1['true_positive']} |",
        f"| FP | {d0['false_positive']} | {l1['false_positive']} | {h1['false_positive']} |",
        f"| FN | {d0['false_negative']} | {l1['false_negative']} | {h1['false_negative']} |",
        f"| Precision | {d0['precision']} | {l1['precision']} | {h1['precision']} |",
        f"| Recall | {d0['recall']} | {l1['recall']} | {h1['recall']} |",
        f"| F1 | {d0['f1']} | {l1['f1']} | {h1['f1']} |",
        f"| Span-only F1 | {span['D0_deterministic']['span_only']['f1']} | {span['L1_learned']['span_only']['f1']} | {span['H1_hybrid']['span_only']['f1']} |",
        "",
        "## Merge Diagnostics",
        "",
    ]
    for key, value in trial["merge_diagnostics"].items():
        if key != "per_example":
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Latency", ""])
    for key, value in trial["latency"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Label Mapping", "", "| Raw label | Canonical label | Status |", "|---|---|---|"])
    for row in label_mapping_table(trial["model_metadata"].get("id2label", {})):
        lines.append(f"| {row['raw_model_label']} | {row['canonical_label']} | {row['mapping_status']} |")
    lines.extend(["", "## Target Gaps", ""])
    for entity_type in TARGET_GAP_TYPES:
        d0_type = trial["systems"]["D0_deterministic"]["per_type"][entity_type]
        l1_type = trial["systems"]["L1_learned"]["per_type"][entity_type]
        h1_type = trial["systems"]["H1_hybrid"]["per_type"][entity_type]
        lines.append(f"- {entity_type}: D0 F1 {d0_type['f1']}, L1 F1 {l1_type['f1']}, H1 F1 {h1_type['f1']}")
    lines.extend(["", "## Shared Types", ""])
    for entity_type in SHARED_TYPES:
        d0_type = trial["systems"]["D0_deterministic"]["per_type"][entity_type]
        l1_type = trial["systems"]["L1_learned"]["per_type"][entity_type]
        h1_type = trial["systems"]["H1_hybrid"]["per_type"][entity_type]
        lines.append(f"- {entity_type}: D0 F1 {d0_type['f1']}, L1 F1 {l1_type['f1']}, H1 F1 {h1_type['f1']}")
    lines.extend(["", "## Protected Regression Check", ""])
    lines.append(f"- Regression count: {trial['protected_type_regression_check']['regression_count']}")
    for entity_type in PROTECTED_CHECK_TYPES:
        d0_type = trial["systems"]["D0_deterministic"]["per_type"][entity_type]
        h1_type = trial["systems"]["H1_hybrid"]["per_type"][entity_type]
        lines.append(f"- {entity_type}: D0 TP/FP {d0_type['true_positive']}/{d0_type['false_positive']}; H1 TP/FP {h1_type['true_positive']}/{h1_type['false_positive']}")
    lines.extend(["", "## Zero-Entity Guardrails", ""])
    for item in trial["zero_entity_guardrails"]:
        lines.append(f"- {item['example_id']}: L1 FP {item['l1_false_positive_count']}; H1 FP {item['h1_false_positive_count']}")
    lines.extend(["", "## New TP/FP Analysis", ""])
    lines.append(f"- learned_filled_fn: {trial['new_true_positive_analysis']['learned_filled_fn']}")
    lines.append(f"- learned_filled_fn by type: `{trial['new_true_positive_analysis']['by_type']}`")
    lines.append(f"- learned_only_new_fp: {trial['new_false_positive_analysis']['learned_only_new_fp']}")
    lines.append(f"- hybrid_new_fp: {trial['new_false_positive_analysis']['hybrid_new_fp']}")
    lines.extend(["", "## Error Taxonomy", ""])
    lines.append(f"- L1: `{trial['error_taxonomy']['L1_learned']['error_type_counts']}`")
    lines.append(f"- H1: `{trial['error_taxonomy']['H1_hybrid']['error_type_counts']}`")
    lines.extend(["", "## Important Examples", ""])
    for item in trial["important_examples"]:
        raw_labels = ", ".join(item["raw_model_labels"]) if item["raw_model_labels"] else "none"
        lines.append(f"- {item['example_id']}: gold {len(item['gold'])}; D0 {len(item['D0'])}; L1 {len(item['L1'])}; H1 {len(item['H1'])}; raw labels {raw_labels}")
    lines.extend(["", "## Boundary Findings", ""])
    for entity_type, records in trial["boundary_analysis"].items():
        exact_count = sum(1 for item in records if item["status"] == "exact_boundary")
        mismatch_count = sum(1 for item in records if item["status"] == "boundary_mismatch")
        lines.append(f"- {entity_type}: exact {exact_count}; boundary mismatches {mismatch_count}")
    lines.extend(["", "## Limitations", ""])
    for item in trial["candidate_limitations_recorded_before_evaluation"] + [
        "only 36 gold examples",
        "one reviewer",
        "short synthetic/legal-style queries",
        "no fine-tuning",
        "no judgment-document evaluation",
        "no statistical superiority claim",
    ]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-predictions", type=Path, help="Evaluate an existing raw prediction payload instead of running the model.")
    args = parser.parse_args()
    gold_payload = load_gold_payload()
    if args.raw_predictions:
        raw_payload = json.loads(args.raw_predictions.read_text(encoding="utf-8"))
        model_metadata = raw_payload.get("model_metadata", {"model_id": MODEL_ID})
        label_mapping = label_mapping_table(model_metadata.get("id2label", {}))
    else:
        raw_payload, model_metadata, label_mapping = run_model(gold_payload)
    evaluation = evaluate_from_raw(raw_payload, model_metadata, PRIMARY_THRESHOLD)
    write_outputs(evaluation, raw_payload, label_mapping)
    print(json.dumps({"candidate": MODEL_ID, "decision": evaluation["trial"]["decision"], "systems": evaluation["trial"]["systems"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
