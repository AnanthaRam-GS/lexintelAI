"""Tests for the frozen grounded answer evaluation foundation."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "data/structured/manifests"


class LegalAnswerEvalFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.eval_manifest = json.loads((MANIFEST_DIR / "legal_answer_eval.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((MANIFEST_DIR / "legal_answer_eval_summary.json").read_text(encoding="utf-8"))
        cls.reviews = json.loads((MANIFEST_DIR / "legal_answer_eval_reviews.json").read_text(encoding="utf-8"))
        cls.pair_map = json.loads((MANIFEST_DIR / "legal_answer_eval_pair_map.json").read_text(encoding="utf-8"))
        cls.outputs = json.loads((MANIFEST_DIR / "legal_answer_eval_outputs.json").read_text(encoding="utf-8"))
        cls.examples = cls.eval_manifest["examples"]

    def test_exact_count_modes_difficulty_and_unique_ids(self) -> None:
        self.assertEqual(len(self.examples), 30)
        self.assertEqual(Counter(example["mode"] for example in self.examples), {"public": 15, "professional": 15})
        self.assertEqual(Counter(example["difficulty"] for example in self.examples), {"basic": 10, "moderate": 10, "hard": 10})
        ids = [example["example_id"] for example in self.examples]
        self.assertEqual(ids, [f"ans-q{index:03d}" for index in range(1, 31)])
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_coverage_is_frozen(self) -> None:
        category_counts = Counter(category for example in self.examples for category in example["category"])
        self.assertGreaterEqual(category_counts["mixed_transition"], 4)
        self.assertGreaterEqual(category_counts["special_statute"], 4)
        self.assertGreaterEqual(category_counts["explicit_section"], 6)
        self.assertGreaterEqual(category_counts["plain_language_public"], 8)
        self.assertGreaterEqual(category_counts["negative_out_of_scope"], 3)
        self.assertEqual(self.summary["coverage_counts"]["transition_cases"], category_counts["mixed_transition"])
        self.assertEqual(self.summary["coverage_counts"]["special_law_cases"], category_counts["special_statute"])

    def test_examples_and_reviews_remain_unscored(self) -> None:
        """The frozen example manifest and reviews stay pending regardless of generation state (Phase 0.9C-B only generates model outputs, never human scores)."""
        forbidden = {"ideal_answer", "reference_answer", "model_answer", "citation_suggestions", "retrieved_case_names"}
        for example in self.examples:
            self.assertFalse(forbidden.intersection(example))
            self.assertEqual(example["review_status"], "pending")
            self.assertIsNone(example["human_scores"])
        self.assertEqual(self.reviews["reviews"], [])

    def test_generated_outputs_cover_every_example_and_condition_exactly_once(self) -> None:
        """After Phase 0.9C-B generation, outputs.json holds exactly one record per (example, condition) pair."""
        self.assertEqual(self.outputs["generation_status"], "completed")
        outputs = self.outputs["outputs"]
        self.assertEqual(len(outputs), 60)
        keys = [(record["example_id"], record["condition"]) for record in outputs]
        self.assertEqual(len(keys), len(set(keys)))
        expected_keys = {(example["example_id"], condition) for example in self.examples for condition in ("LLM_ONLY", "GROUNDED_RAG")}
        self.assertEqual(set(keys), expected_keys)

    def test_rubric_dimensions_scales_and_composite_are_frozen(self) -> None:
        rubric = self.eval_manifest["rubric"]
        self.assertEqual(set(rubric["positive_scale"]), {"0", "1", "2", "3", "4"})
        self.assertEqual(set(rubric["hallucination_scale"]), {"0", "1", "2", "3"})
        expected = {
            "LEGAL_RELEVANCE",
            "LEGAL_CORRECTNESS",
            "GROUNDING_SUPPORT",
            "CITATION_QUALITY",
            "COMPLETENESS",
            "UNCERTAINTY_HANDLING",
            "REGIME_HANDLING",
            "ACTIONABILITY",
            "HALLUCINATION_SEVERITY",
            "OVERALL_PREFERENCE",
        }
        self.assertEqual(set(rubric["dimensions"]), expected)
        self.assertIn("mean(LEGAL_RELEVANCE", rubric["quality_composite_formula"])
        self.assertTrue(rubric["hallucination_reported_separately"])

    def test_pairing_is_deterministic_balanced_and_concealed(self) -> None:
        pairs = self.pair_map["pairs"]
        self.assertEqual(self.pair_map["randomization_seed"], 90210)
        self.assertTrue(self.pair_map["concealed_from_reviewer_packet"])
        self.assertEqual([pair["example_id"] for pair in pairs], [example["example_id"] for example in self.examples])
        self.assertEqual(Counter(pair["display_A_condition"] for pair in pairs), {"LLM_ONLY": 15, "GROUNDED_RAG": 15})
        self.assertEqual(Counter(pair["display_B_condition"] for pair in pairs), {"LLM_ONLY": 15, "GROUNDED_RAG": 15})
        self.assertTrue(all(pair["display_A_condition"] != pair["display_B_condition"] for pair in pairs))
        review_packet = (ROOT / "docs/LEGAL_ANSWER_EVAL_REVIEW.md").read_text(encoding="utf-8")
        self.assertNotIn("LLM_ONLY", review_packet)
        self.assertNotIn("GROUNDED_RAG", review_packet)

    def test_component_hashes_record_frozen_sources(self) -> None:
        for relative_path, expected_digest in self.eval_manifest["component_hashes"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest(), expected_digest)

    def test_evaluator_reports_completion_state_matching_actual_success_rate(self) -> None:
        """A benchmark run that completed but left some slots failed must never be reported as ready for review."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "backend/scripts/evaluate_grounded_legal_answers.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        outputs = self.outputs["outputs"]
        successful = sum(1 for record in outputs if record.get("generation_status") == "SUCCESS")
        expected_status = "OUTPUTS_READY_FOR_BLINDED_HUMAN_REVIEW" if successful == len(outputs) else "GENERATION_COMPLETED_WITH_FAILURES"
        self.assertEqual(payload["status"], expected_status)

    def test_evaluator_distinguishes_partial_failures_from_full_success(self) -> None:
        example_keys = [(example["example_id"], condition) for example in self.examples for condition in ("LLM_ONLY", "GROUNDED_RAG")]
        with tempfile.TemporaryDirectory() as tmp_dir:
            all_success_path = Path(tmp_dir) / "outputs_all_success.json"
            all_success_path.write_text(
                json.dumps(
                    {
                        "generation_status": "completed",
                        "outputs": [{"example_id": eid, "condition": cond, "generation_status": "SUCCESS"} for eid, cond in example_keys],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "backend/scripts/evaluate_grounded_legal_answers.py"), "--outputs-path", str(all_success_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout)["status"], "OUTPUTS_READY_FOR_BLINDED_HUMAN_REVIEW")

            partial_path = Path(tmp_dir) / "outputs_partial.json"
            outputs = [{"example_id": eid, "condition": cond, "generation_status": "SUCCESS"} for eid, cond in example_keys]
            outputs[0]["generation_status"] = "FAILED_PROVIDER"
            partial_path.write_text(json.dumps({"generation_status": "completed", "outputs": outputs}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "backend/scripts/evaluate_grounded_legal_answers.py"), "--outputs-path", str(partial_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout)["status"], "GENERATION_COMPLETED_WITH_FAILURES")

    def test_evaluator_reports_ready_for_generation_before_outputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            not_started_path = Path(tmp_dir) / "outputs_not_started.json"
            not_started_path.write_text(json.dumps({"generation_status": "not_started", "outputs": []}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend/scripts/evaluate_grounded_legal_answers.py"),
                    "--outputs-path",
                    str(not_started_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout)["status"], "READY_FOR_GENERATION_OR_REVIEW")

    def test_generation_harness_is_dry_run_only(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "backend/scripts/run_grounded_answer_eval_generation.py"), "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DRY_RUN_ONLY")
        self.assertFalse(payload["live_generation_executed"])
        self.assertEqual(payload["llm_calls"], 0)
        self.assertEqual(payload["planned_outputs"], 60)


if __name__ == "__main__":
    unittest.main()
