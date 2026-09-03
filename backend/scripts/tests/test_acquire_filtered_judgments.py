"""Tests for V2 filtered judgment acquisition orchestration."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
