import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from backend.scripts.validate_legal_ner_eval import MATERIALIZED_ENTITY_TYPE_COUNTS, validate_gold_template


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_eval.json"
TEMPLATE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json"
REVIEW_PATH = REPO_ROOT / "docs/LEGAL_NER_GOLD_REVIEW.md"
SCHEMA_PATH = REPO_ROOT / "backend/app/schemas/legal_ner.py"


class LegalNERGoldWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
        self.template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

    def test_template_has_36_reviewed_examples(self) -> None:
        self.assertEqual(self.template["schema_version"], "legalai-ner-schema-v1")
        self.assertEqual(self.template["annotation_status"], "human_gold_materialized")
        self.assertEqual(len(self.template["examples"]), 36)
        self.assertEqual(sum(1 for example in self.template["examples"] if example["review_status"] == "pending"), 0)
        self.assertEqual(sum(1 for example in self.template["examples"] if example["review_status"] == "reviewed"), 36)
        self.assertEqual(sum(len(example["gold_entities"]) for example in self.template["examples"]), 89)
        self.assertEqual({example["reviewer"] for example in self.template["examples"]}, {"Ananthu"})

    def test_template_text_identity_with_eval_manifest(self) -> None:
        source = [(example["example_id"], example["text"]) for example in self.source["examples"]]
        template = [(example["example_id"], example["text"]) for example in self.template["examples"]]
        self.assertEqual(template, source)

    def test_template_validator_accepts_materialized_state(self) -> None:
        self.assertEqual(validate_gold_template(), [])

    def test_materialized_type_counts(self) -> None:
        counts = Counter(entity["entity_type"] for example in self.template["examples"] for entity in example["gold_entities"])
        self.assertEqual(dict(counts), MATERIALIZED_ENTITY_TYPE_COUNTS)

    def test_materialized_zero_entity_examples(self) -> None:
        zero = [example["example_id"] for example in self.template["examples"] if not example["gold_entities"]]
        self.assertEqual(zero, ["ner-q026", "ner-q036"])

    def test_all_materialized_spans_match_exact_text(self) -> None:
        for example in self.template["examples"]:
            text = example["text"]
            for entity in example["gold_entities"]:
                self.assertEqual(text[entity["start_char"] : entity["end_char"]], entity["text"])

    def test_batch_partition_is_9_each(self) -> None:
        text = REVIEW_PATH.read_text(encoding="utf-8")
        self.assertEqual(text.count("## Batch "), 4)
        self.assertIn("## Batch 1: ner-q001 to ner-q009", text)
        self.assertIn("## Batch 2: ner-q010 to ner-q018", text)
        self.assertIn("## Batch 3: ner-q019 to ner-q027", text)
        self.assertIn("## Batch 4: ner-q028 to ner-q036", text)
        for example in self.template["examples"]:
            self.assertIn(f"### {example['example_id']}", text)
            self.assertIn(example["text"], text)
        self.assertEqual(text.count("| Entity text | Type | Start | End | Notes |"), 36)

    def test_valid_offsets_and_exact_span_match_pass(self) -> None:
        payload = copy.deepcopy(self.template)
        payload["annotation_status"] = "pending_human_gold_annotation"
        for example in payload["examples"]:
            example["gold_entities"] = []
            example["review_status"] = "pending"
            example.pop("reviewer", None)
            example.pop("reviewed_at", None)
        payload["examples"][0]["gold_entities"] = [{"text": "Section 302", "entity_type": "SECTION", "start_char": 0, "end_char": 11}]
        self.assertEqual(validate_temp(payload), [])

    def test_invalid_type_is_rejected(self) -> None:
        payload = copy.deepcopy(self.template)
        payload["examples"][0]["gold_entities"] = [{"text": "Section 302", "entity_type": "LAW_SECTION", "start_char": 0, "end_char": 11}]
        self.assertIn("invalid entity_type LAW_SECTION", "\n".join(validate_temp(payload)))

    def test_invalid_offset_is_rejected(self) -> None:
        payload = copy.deepcopy(self.template)
        payload["examples"][0]["gold_entities"] = [{"text": "Section 302", "entity_type": "SECTION", "start_char": -1, "end_char": 11}]
        self.assertIn("start_char must be >= 0", "\n".join(validate_temp(payload)))

    def test_span_text_mismatch_is_rejected(self) -> None:
        payload = copy.deepcopy(self.template)
        payload["examples"][0]["gold_entities"] = [{"text": "Section 303", "entity_type": "SECTION", "start_char": 0, "end_char": 11}]
        self.assertIn("text does not match exact source span", "\n".join(validate_temp(payload)))

    def test_duplicate_entity_key_is_rejected(self) -> None:
        payload = copy.deepcopy(self.template)
        entity = {"text": "Section 302", "entity_type": "SECTION", "start_char": 0, "end_char": 11}
        payload["examples"][0]["gold_entities"] = [entity, entity]
        self.assertIn("duplicates entity key", "\n".join(validate_temp(payload)))

    def test_reviewed_zero_entity_allowed(self) -> None:
        payload = copy.deepcopy(self.template)
        payload["annotation_status"] = "pending_human_gold_annotation"
        payload["examples"][25]["review_status"] = "reviewed"
        payload["examples"][25]["gold_entities"] = []
        self.assertEqual(validate_temp(payload), [])

    def test_schema_unchanged(self) -> None:
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertIn('NER_SCHEMA_VERSION = "legalai-ner-schema-v1"', schema_text)
        self.assertIn('"FIR_NUMBER"', schema_text)
        self.assertIn('"POLICE_STATION"', schema_text)

    def test_retrieval_freeze_unchanged(self) -> None:
        selected = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        decision = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_tuning_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertEqual(selected["final_top_k"], 5)
        self.assertFalse(selected["experimental_features"]["regime_ranking_enabled"])
        self.assertFalse(decision["frozen_benchmark_rerun_required"])


def validate_temp(payload: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "legal_ner_gold_template.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return validate_gold_template(path=path)


if __name__ == "__main__":
    unittest.main()
