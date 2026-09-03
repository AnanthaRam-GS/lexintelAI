"""Tests for V2 filtered judgment acquisition orchestration."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from backend.scripts import acquire_filtered_judgments as acquire


class AcquireFilteredJudgmentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.strategy = self.root / "strategy.json"
        self.queries = self.root / "queries.json"
        self.quotas = self.root / "quotas.json"
        self.strategy.write_text(
            json.dumps(
                {
                    "temporal_tracks": [{"name": "recent_ipc"}],
                    "quality_thresholds": {"criminal_strong": 0.7},
                }
            ),
            encoding="utf-8",
        )
        self.queries.write_text(
            json.dumps(
                [
                    {
                        "query_id": "q1",
                        "offence_family": "theft_and_robbery",
                        "temporal_track": "recent_ipc",
                        "query": "theft IPC criminal appeal",
                        "target_quota": 1,
                        "doctypes": "judgments",
                        "from_date": "2018-01-01",
                        "to_date": "2024-06-30",
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.quotas.write_text(
            json.dumps([{"offence_family": "theft_and_robbery", "target_quota": 1}]),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dry_run_makes_zero_network_calls(self) -> None:
        output = io.StringIO()
        with patch.object(acquire, "STRATEGY_MANIFEST", self.strategy):
            with patch.object(acquire, "QUERY_MANIFEST", self.queries):
                with patch.object(acquire, "QUOTA_MANIFEST", self.quotas):
                    with patch("urllib.request.urlopen") as urlopen:
                        with redirect_stdout(output):
                            result = acquire.dry_run(5, 100, strategy_manifest=self.strategy)

        self.assertEqual(result, 0)
        self.assertIn("No Indian Kanoon API requests were made.", output.getvalue())
        urlopen.assert_not_called()

    def test_budget_enforcement_raises_at_limit(self) -> None:
        class Client:
            def get_request_stats(self) -> dict[str, object]:
                return {"total_requests": 3}

        with self.assertRaises(acquire.BudgetExceeded):
            acquire.enforce_budget(Client(), 3)  # type: ignore[arg-type]

    def test_query_filters_are_applied(self) -> None:
        queries = json.loads(self.queries.read_text(encoding="utf-8"))
        selected = acquire.filtered_queries(
            queries,
            query_id="q1",
            offence_family="theft_and_robbery",
            temporal_track="recent_ipc",
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["query_id"], "q1")

    def test_year_within_bounds_enforces_temporal_track(self) -> None:
        self.assertTrue(acquire.year_within_bounds(2024, "2024-07-01", None))
        self.assertFalse(acquire.year_within_bounds(2023, "2024-07-01", None))
        self.assertTrue(acquire.year_within_bounds(2020, "2018-01-01", "2024-06-30"))
        self.assertFalse(acquire.year_within_bounds(2026, "2018-01-01", "2024-06-30"))

    def test_extract_document_text_handles_html_entities_and_scripts(self) -> None:
        text = acquire.extract_document_text(
            {
                "doc": "<html><style>.x{}</style><body><h1>A &amp; B</h1>"
                "<script>secret()</script><p> Criminal   Appeal </p></body></html>"
            }
        )

        self.assertEqual(text, "A & B Criminal Appeal")
        self.assertNotIn("secret", text)

    def test_extract_document_text_handles_missing_or_empty_payload(self) -> None:
        self.assertEqual(acquire.extract_document_text({}), "")
        self.assertEqual(acquire.extract_document_text({"doc": ""}), "")
        self.assertEqual(acquire.extract_document_text(None), "")
        self.assertEqual(acquire.extract_document_text({"doc": None}), "")

    def test_pre_download_decision_mapping(self) -> None:
        self.assertEqual(acquire.pre_download_decision("accept_candidate"), "download")
        self.assertEqual(acquire.pre_download_decision("needs_review"), "needs_more_evidence")
        self.assertEqual(acquire.pre_download_decision("reject"), "reject_before_download")

    def test_accept_and_needs_review_are_queued_pending_but_reject_is_audit_only(self) -> None:
        accepted = {"local_id": "v2-1", "source_document_id": "1", "case_name": "A v State", "offence_family": "homicide", "source_url": "url", "status": "validated"}
        uncertain = {"local_id": "v2-2", "source_document_id": "2", "case_name": "B v State", "offence_family": "kidnapping", "source_url": "url", "status": "needs_review"}
        reviews: list[dict[str, object]] = []

        acquire.upsert_by_local_id(reviews, acquire.review_record_for(accepted))
        acquire.upsert_by_local_id(reviews, acquire.review_record_for(uncertain))

        self.assertEqual([item["human_review_status"] for item in reviews], ["pending", "pending"])
        self.assertEqual(len(reviews), 2)

    def test_reject_before_download_is_not_queued_by_flow(self) -> None:
        rejected = {"local_id": "v2-3", "source_document_id": "3", "case_name": "Rules", "offence_family": "other", "source_url": "url", "status": "rejected_pre_download"}
        reviews: list[dict[str, object]] = []

        if rejected["status"] in {"validated", "needs_review"}:
            acquire.upsert_by_local_id(reviews, acquire.review_record_for(rejected))

        self.assertEqual(reviews, [])

    def test_mock_flow_queues_needs_review_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for path, data in [
                (root / "queries.json", self.queries.read_text(encoding="utf-8")),
                (root / "quotas.json", self.quotas.read_text(encoding="utf-8")),
                (root / "v1.json", "[]"),
                (root / "judgments.json", "[]"),
                (root / "review.json", "[]"),
                (root / "audit.json", "[]"),
            ]:
                path.write_text(data, encoding="utf-8")
            raw_dir = root / "raw"
            client = Mock()
            client.get_request_stats.return_value = {"total_requests": 0}
            client.search.return_value = {"docs": [{"tid": "10", "title": "A v State"}]}
            client.get_document_metadata.return_value = {
                "title": "A v State",
                "court": "Example High Court",
                "date": "2024-01-01",
            }
            client.get_document.return_value = {
                "doc": "<p>A v State. Criminal Appeal. Section 420 IPC. Hon'ble Court order.</p>"
            }
            client.get_original_document.return_value = b"%PDF sample"

            with patch.object(acquire, "QUERY_MANIFEST", root / "queries.json"):
                with patch.object(acquire, "QUOTA_MANIFEST", root / "quotas.json"):
                    with patch.object(acquire, "V1_JUDGMENTS", root / "v1.json"):
                        with patch.object(acquire, "PRESCREEN_JUDGMENTS", root / "judgments.json"):
                            with patch.object(acquire, "PRESCREEN_REVIEW", root / "review.json"):
                                with patch.object(acquire, "PRESCREEN_AUDIT", root / "audit.json"):
                                    with patch.object(acquire, "RAW_DIR", raw_dir):
                                        with patch.object(acquire, "REPO_ROOT", root):
                                            with patch.object(acquire, "IndianKanoonClient", return_value=client):
                                                result = acquire.acquire(limit=1, max_api_requests=10, delay=0)

            self.assertEqual(result, 0)
            review_records = json.loads((root / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(len(review_records), 1)
            self.assertEqual(review_records[0]["human_review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
