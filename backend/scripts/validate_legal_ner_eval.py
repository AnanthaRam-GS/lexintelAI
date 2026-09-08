"""Validate the LegalAI NER evaluation manifest contract."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_eval.json"
EXPECTED_VERSION = "legalai-ner-eval-v1"
NER_SCHEMA_VERSION = "legalai-ner-schema-v1"
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


def main() -> int:
    errors = validate_manifest()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"NER evaluation manifest valid: {len(payload['examples'])} examples pending human gold annotation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
