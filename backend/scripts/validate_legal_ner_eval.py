"""Validate the LegalAI NER evaluation manifest contract."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_eval.json"
GOLD_TEMPLATE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json"
EXPECTED_VERSION = "legalai-ner-eval-v1"
EXPECTED_GOLD_TEMPLATE_VERSION = "legalai-ner-gold-template-v1"
NER_SCHEMA_VERSION = "legalai-ner-schema-v1"
REVIEW_STATUSES = {"pending", "reviewed", "needs_revision"}
CANONICAL_ENTITY_TYPES = (
    "PERSON",
    "ORGANIZATION",
    "COURT",
    "LOCATION",
    "DATE",
    "STATUTE",
    "SECTION",
    "CASE_CITATION",
    "CASE_NAME",
    "LEGAL_PROCEDURE",
    "OFFENCE",
    "LEGAL_ROLE",
    "POLICE_STATION",
    "FIR_NUMBER",
)


def validate_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("version") != EXPECTED_VERSION:
        errors.append("unexpected manifest version")
    if payload.get("schema_version") != NER_SCHEMA_VERSION:
        errors.append("unexpected schema version")
    examples = payload.get("examples")
    if not isinstance(examples, list) or not 30 <= len(examples) <= 50:
        errors.append("manifest must contain 30-50 examples")
        examples = []
    seen_ids: set[str] = set()
    valid_types = set(CANONICAL_ENTITY_TYPES)
    for index, example in enumerate(examples, start=1):
        example_id = example.get("example_id")
        text = example.get("text")
        if not isinstance(example_id, str) or not example_id:
            errors.append(f"example {index} missing example_id")
        elif example_id in seen_ids:
            errors.append(f"duplicate example_id {example_id}")
        seen_ids.add(example_id)
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{example_id} missing text")
        if example.get("review_status") != "pending":
            errors.append(f"{example_id} must remain pending before human review")
        gold = example.get("gold_entities")
        if gold != []:
            errors.append(f"{example_id} gold_entities must be empty before human review")
        for entity in gold or []:
            if entity.get("entity_type") not in valid_types:
                errors.append(f"{example_id} has invalid entity type {entity.get('entity_type')}")
    return errors


def validate_gold_template(path: Path = GOLD_TEMPLATE_PATH, source_path: Path = MANIFEST_PATH) -> list[str]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("version") != EXPECTED_GOLD_TEMPLATE_VERSION:
        errors.append("unexpected gold template version")
    if payload.get("schema_version") != NER_SCHEMA_VERSION:
        errors.append("unexpected schema version")
    if payload.get("annotation_status") != "pending_human_gold_annotation":
        errors.append("annotation_status must remain pending_human_gold_annotation")
    source_examples = source.get("examples", [])
    examples = payload.get("examples", [])
    if len(source_examples) != 36:
        errors.append("source NER eval manifest must contain exactly 36 examples")
    if len(examples) != 36:
        errors.append("gold template must contain exactly 36 examples")
    source_text_by_id = {example.get("example_id"): example.get("text") for example in source_examples}
    seen_ids: set[str] = set()
    valid_types = set(CANONICAL_ENTITY_TYPES)
    for index, example in enumerate(examples, start=1):
        example_id = example.get("example_id")
        text = example.get("text")
        if not isinstance(example_id, str) or not example_id:
            errors.append(f"example {index} missing example_id")
            continue
        if example_id in seen_ids:
            errors.append(f"duplicate example_id {example_id}")
        seen_ids.add(example_id)
        if example_id not in source_text_by_id:
            errors.append(f"{example_id} not present in source NER eval manifest")
        elif text != source_text_by_id[example_id]:
            errors.append(f"{example_id} text changed from source NER eval manifest")
        if example.get("review_status") not in REVIEW_STATUSES:
            errors.append(f"{example_id} has invalid review_status {example.get('review_status')}")
        if not isinstance(text, str):
            errors.append(f"{example_id} text must be a string")
            text = ""
        gold = example.get("gold_entities")
        if not isinstance(gold, list):
            errors.append(f"{example_id} gold_entities must be a list")
            gold = []
        seen_entities: set[tuple[int, int, str]] = set()
        for entity_index, entity in enumerate(gold, start=1):
            entity_type = entity.get("entity_type")
            start = entity.get("start_char")
            end = entity.get("end_char")
            entity_text = entity.get("text")
            label = f"{example_id} entity {entity_index}"
            if entity_type not in valid_types:
                errors.append(f"{label} invalid entity_type {entity_type}")
            if not isinstance(start, int) or start < 0:
                errors.append(f"{label} start_char must be >= 0")
                continue
            if not isinstance(end, int) or end <= start:
                errors.append(f"{label} end_char must be greater than start_char")
                continue
            if end > len(text):
                errors.append(f"{label} end_char exceeds text length")
                continue
            if text[start:end] != entity_text:
                errors.append(f"{label} text does not match exact source span")
            key = (start, end, str(entity_type))
            if key in seen_entities:
                errors.append(f"{label} duplicates entity key {key}")
            seen_entities.add(key)
    return errors


def main() -> int:
    errors = validate_manifest()
    if GOLD_TEMPLATE_PATH.exists():
        errors.extend(validate_gold_template())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    message = f"NER evaluation manifest valid: {len(payload['examples'])} examples pending human gold annotation"
    if GOLD_TEMPLATE_PATH.exists():
        gold = json.loads(GOLD_TEMPLATE_PATH.read_text(encoding="utf-8"))
        pending = sum(1 for example in gold["examples"] if example["review_status"] == "pending")
        reviewed = sum(1 for example in gold["examples"] if example["review_status"] == "reviewed")
        entities = sum(len(example["gold_entities"]) for example in gold["examples"])
        message += f"; gold template valid: {len(gold['examples'])} examples, {pending} pending, {reviewed} reviewed, {entities} gold entities"
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
