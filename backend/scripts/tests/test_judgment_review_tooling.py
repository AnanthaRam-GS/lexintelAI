"""Tests for development judgment human review support tooling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scripts import generate_judgment_review_report as report
from backend.scripts import review_development_judgment as review


class JudgmentReviewToolingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.judgment_manifest = self.root / "development_judgments.json"
        self.review_manifest = self.root / "development_judgment_review.json"
        self.query_manifest = self.root / "development_judgment_queries.json"
        self.raw_dir = self.root / "data/raw/judgments/indiankanoon"
        self.raw_dir.mkdir(parents=True)
        self.raw_path = self.raw_dir / "sample.html"
        self.raw_path.write_text("<html><body> Sample judgment text. </body></html>", encoding="utf-8")
        self.judgments = [
            {
                "local_id": "dev-1",
                "source_provider": "indian_kanoon",
                "source_document_id": "1",
                "source_url": "https://indiankanoon.org/doc/1/",
                "case_name": "A v State",
                "case_number": None,
                "court_name": "Example High Court",
                "court_level": "high_court",
                "decision_date": None,
                "year": 2024,
                "legal_regime": "unknown",
                "offence_family": "homicide",
                "known_sections": [],
                "acquisition_query": "murder criminal appeal",
                "retrieval_rank": 1,
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "raw_file_path": str(self.raw_path.relative_to(self.root)),
                "sha256": "abc",
                "file_size_bytes": self.raw_path.stat().st_size,
                "mime_type": "text/html",
                "attribution_required": True,
                "attribution_text": "Judgment data sourced from Indian Kanoon API.",
                "status": "validated",
                "notes": None,
            },
            {
                "local_id": "dev-2",
                "source_provider": "indian_kanoon",
                "source_document_id": "2",
                "source_url": "https://indiankanoon.org/doc/2/",
                "case_name": "Duplicate",
                "court_level": "high_court",
                "year": 2024,
                "legal_regime": "unknown",
                "offence_family": "homicide",
                "raw_file_path": None,
                "sha256": "abc",
                "file_size_bytes": None,
                "mime_type": "application/pdf",
                "attribution_required": True,
                "status": "excluded_duplicate",
            },
        ]
        self.reviews = [
            {
                "local_id": "dev-1",
                "source_document_id": "1",
                "case_name": "A v State",
                "offence_family": "homicide",
                "source_url": "https://indiankanoon.org/doc/1/",
                "automated_status": "validated",
                "human_review_status": "pending",
                "review_notes": None,
            }
        ]
        self.queries = [
            {"query_id": "homicide", "offence_family": "homicide"},
            {"query_id": "hurt", "offence_family": "hurt_and_assault"},
        ]
        self.write_manifests()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_manifests(self) -> None:
        self.judgment_manifest.write_text(json.dumps(self.judgments), encoding="utf-8")
        self.review_manifest.write_text(json.dumps(self.reviews), encoding="utf-8")
        self.query_manifest.write_text(json.dumps(self.queries), encoding="utf-8")

    def load_judgments(self) -> list[dict[str, object]]:
        return json.loads(self.judgment_manifest.read_text(encoding="utf-8"))

    def load_reviews(self) -> list[dict[str, object]]:
        return json.loads(self.review_manifest.read_text(encoding="utf-8"))

    def update(self, **kwargs: object) -> None:
        review.update_review(
            judgment_manifest=self.judgment_manifest,
            review_manifest=self.review_manifest,
            query_manifest=self.query_manifest,
            **kwargs,
        )

    def test_report_generation_does_not_modify_review_statuses(self) -> None:
        before = self.load_reviews()
        out = self.root / "review.md"
        represented, available, unavailable = report.generate_report(
            judgment_manifest=self.judgment_manifest,
            review_manifest=self.review_manifest,
            report_path=out,
            repo_root=self.root,
        )

        self.assertEqual(self.load_reviews(), before)
        self.assertEqual(represented, 1)
        self.assertEqual(available, 1)
        self.assertEqual(unavailable, 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("## dev-1 — A v State", text)
        self.assertIn("* [ ] Genuine judicial decision/order", text)
        self.assertNotIn("dev-2", text)

    def test_unknown_source_id_rejected(self) -> None:
        with self.assertRaisesRegex(review.ReviewError, "unknown source_document_id"):
            self.update(source_id="missing", decision="accepted")

    def test_accepted_decision_updates_only_intended_review_record(self) -> None:
        before_judgment = self.load_judgments()[0].copy()
        self.update(
            source_id="1",
            decision="accepted",
            offence_family="hurt_and_assault",
            legal_regime="ipc_crpc",
            notes="Reviewed by a human.",
        )

        updated_review = self.load_reviews()[0]
        updated_judgment = self.load_judgments()[0]
        self.assertEqual(updated_review["human_review_status"], "accepted")
        self.assertEqual(updated_review["offence_family"], "hurt_and_assault")
        self.assertEqual(updated_review["legal_regime"], "ipc_crpc")
        self.assertEqual(updated_review["review_notes"], "Reviewed by a human.")
        self.assertEqual(updated_review["reviewer"], None)
        self.assertIn("reviewed_at", updated_review)
        self.assertEqual(updated_judgment["offence_family"], "hurt_and_assault")
        self.assertEqual(updated_judgment["legal_regime"], "ipc_crpc")
        for protected in review.PROTECTED_JUDGMENT_FIELDS:
            self.assertEqual(updated_judgment.get(protected), before_judgment.get(protected))

    def test_rejected_decision_works(self) -> None:
        self.update(source_id="1", decision="rejected", reviewer="Reviewer")
        updated_review = self.load_reviews()[0]
        self.assertEqual(updated_review["human_review_status"], "rejected")
        self.assertEqual(updated_review["reviewer"], "Reviewer")

    def test_needs_review_works(self) -> None:
        self.update(source_id="1", decision="needs_review")
        self.assertEqual(self.load_reviews()[0]["human_review_status"], "needs_review")

    def test_invalid_decision_rejected(self) -> None:
        with self.assertRaisesRegex(review.ReviewError, "invalid decision"):
            self.update(source_id="1", decision="pending")

    def test_invalid_offence_family_rejected(self) -> None:
        with self.assertRaisesRegex(review.ReviewError, "invalid offence_family"):
            self.update(source_id="1", decision="accepted", offence_family="made_up")

    def test_invalid_legal_regime_rejected(self) -> None:
        with self.assertRaisesRegex(review.ReviewError, "invalid legal_regime"):
            self.update(source_id="1", decision="accepted", legal_regime="made_up")

    def test_acquisition_status_remains_unchanged(self) -> None:
        self.update(source_id="1", decision="accepted")
        self.assertEqual(self.load_judgments()[0]["status"], "validated")

    def test_provenance_remains_unchanged(self) -> None:
        before = self.load_judgments()[0]
        self.update(source_id="1", decision="accepted")
        after = self.load_judgments()[0]
        for field in review.PROTECTED_JUDGMENT_FIELDS:
            self.assertEqual(after.get(field), before.get(field))

    def test_manifest_writing_remains_valid_json(self) -> None:
        self.update(source_id="1", decision="accepted", notes="Valid JSON")
        self.assertIsInstance(json.loads(self.review_manifest.read_text(encoding="utf-8")), list)

    def test_no_network_calls_occur(self) -> None:
        with patch("socket.create_connection") as create_connection:
            out = self.root / "review.md"
            report.generate_report(
                judgment_manifest=self.judgment_manifest,
                review_manifest=self.review_manifest,
                report_path=out,
                repo_root=self.root,
            )
            self.update(source_id="1", decision="needs_review")

        create_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
