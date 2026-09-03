"""Tests for controlled development judgment acquisition."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.scripts import acquire_development_judgments as acquire


class AcquireDevelopmentJudgmentsTest(unittest.TestCase):
    def test_limit_policy(self) -> None:
        self.assertEqual(acquire.DEFAULT_LIMIT, 5)
        self.assertEqual(acquire.validate_limit(50), 50)
        with self.assertRaises(acquire.AcquisitionConfigError):
            acquire.validate_limit(0)
        with self.assertRaises(acquire.AcquisitionConfigError):
            acquire.validate_limit(51)

    def test_normalize_court_level(self) -> None:
        self.assertEqual(
            acquire.normalize_court_level("Supreme Court of India"),
            "supreme_court",
        )
        self.assertEqual(
            acquire.normalize_court_level("Madras High Court"),
            "high_court",
        )
        self.assertEqual(
            acquire.normalize_court_level("Sessions Court, Ernakulam"),
            "district_or_sessions",
        )
        self.assertEqual(acquire.normalize_court_level("Unknown Forum"), "unknown")

    def test_duplicate_source_id_behavior(self) -> None:
        records = [{"source_provider": "indian_kanoon", "source_document_id": "123"}]

        self.assertTrue(acquire.source_id_exists("123", records))
        self.assertFalse(acquire.source_id_exists("456", records))

    def test_limit_counts_existing_active_records(self) -> None:
        records = [
            {"status": "validated"},
            {"status": "downloaded"},
            {"status": "excluded_duplicate"},
        ]

        self.assertEqual(acquire.active_record_count(records), 2)

    def test_sha_duplicate_behavior(self) -> None:
        records = [{"local_id": "dev-1", "sha256": "abc"}]

        self.assertEqual(acquire.find_duplicate_by_sha256("abc", records), records[0])
        self.assertIsNone(acquire.find_duplicate_by_sha256("def", records))

    def test_dry_run_makes_no_api_calls(self) -> None:
        queries = [
            {
                "query_id": "q1",
                "offence_family": "homicide",
                "query": "murder",
                "target_count": 3,
            }
        ]

        with patch.object(acquire, "load_manifest", return_value=queries):
            with patch.object(acquire, "IndianKanoonClient") as client_cls:
                result = acquire.acquire(limit=5, dry_run=True)

        self.assertEqual(result, 0)
        client_cls.assert_not_called()

    def test_missing_api_token_is_safe(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = acquire.acquire(limit=5, dry_run=False)

        self.assertEqual(result, 2)

    def test_auth_or_rate_limit_error_stops_acquisition(self) -> None:
        queries = [
            {
                "query_id": "q1",
                "offence_family": "homicide",
                "query": "murder",
                "target_count": 3,
            }
        ]
        client = Mock()
        client.search.side_effect = acquire.IndianKanoonClientError(
            "Indian Kanoon API returned HTTP 403.",
            status_code=403,
        )

        with patch.dict("os.environ", {"INDIAN_KANOON_API_TOKEN": "token"}):
            with patch.object(acquire, "load_manifest", return_value=queries):
                with patch.object(acquire, "IndianKanoonClient", return_value=client):
                    result = acquire.acquire(limit=5, dry_run=False)

        self.assertEqual(result, 1)

    def test_manifest_update_behavior_with_mock_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            query_path = root / "queries.json"
            judgment_path = root / "judgments.json"
            review_path = root / "review.json"
            raw_dir = root / "raw"
            query_path.write_text(
                '[{"query_id":"q1","offence_family":"homicide","query":"murder","target_count":1}]',
                encoding="utf-8",
            )
            judgment_path.write_text("[]", encoding="utf-8")
            review_path.write_text("[]", encoding="utf-8")

            client = Mock()
            client.search.return_value = {"docs": [{"tid": "123", "title": "A v State"}]}
            client.get_document_metadata.return_value = {
                "title": "A v State",
                "court": "Supreme Court of India",
                "date": "2020-01-01",
            }
            client.get_original_document.return_value = b"%PDF sample"

            with patch.dict("os.environ", {"INDIAN_KANOON_API_TOKEN": "token"}):
                with patch.object(acquire, "QUERY_MANIFEST", query_path):
                    with patch.object(acquire, "JUDGMENT_MANIFEST", judgment_path):
                        with patch.object(acquire, "REVIEW_MANIFEST", review_path):
                            with patch.object(acquire, "RAW_DIR", raw_dir):
                                with patch.object(acquire, "REPO_ROOT", root):
                                    with patch.object(acquire, "IndianKanoonClient", return_value=client):
                                        result = acquire.acquire(limit=1, dry_run=False, delay=0)

            self.assertEqual(result, 0)
            self.assertIn('"source_document_id": "123"', judgment_path.read_text(encoding="utf-8"))
            self.assertIn('"human_review_status": "pending"', review_path.read_text(encoding="utf-8"))

    def test_acquire_stops_when_existing_active_count_meets_limit(self) -> None:
        existing = [{"status": "validated", "source_provider": "indian_kanoon"}]
        with patch.dict("os.environ", {"INDIAN_KANOON_API_TOKEN": "token"}):
            with patch.object(acquire, "load_manifest", side_effect=[[{"query_id": "q1"}], existing, []]):
                with patch.object(acquire, "IndianKanoonClient") as client_cls:
                    result = acquire.acquire(limit=1, dry_run=False)

        self.assertEqual(result, 0)
        client_cls.assert_not_called()

    def test_original_document_json_payload_is_decoded(self) -> None:
        payload = (
            b'{"Content-Type":"application/pdf","doc":"JVBERiBzYW1wbGU="}'
        )

        content, mime_type = acquire.normalize_original_document_payload(payload)

        self.assertEqual(content, b"%PDF sample")
        self.assertEqual(mime_type, "application/pdf")


if __name__ == "__main__":
    unittest.main()
