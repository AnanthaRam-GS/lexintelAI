"""Tests for durable bulk acquisition state helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.scripts import bulk_acquisition_state as bulk


class BulkAcquisitionStateTest(unittest.TestCase):
    def test_run_id_generation_and_validation(self) -> None:
        run_id = bulk.generate_run_id(datetime(2026, 9, 4, 6, 0, 0, tzinfo=UTC))

        self.assertRegex(run_id, bulk.RUN_ID_PATTERN)
        self.assertEqual(bulk.validate_run_id(run_id), run_id)
        with self.assertRaises(ValueError):
            bulk.validate_run_id("bulk_bad")

    def test_start_new_run_does_not_overwrite_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = bulk.create_run_state(
                "bulk_20260904_060000_abcd",
                strategy_version="v2",
                query_manifest="queries.json",
                target_count=10,
                api_budget=100,
                partitions=[],
            )

            bulk.start_new_run(root, state)

            with self.assertRaises(FileExistsError):
                bulk.start_new_run(root, state)

    def test_resume_loads_checkpoint_seen_sets_and_retry_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = bulk.create_run_state(
                "bulk_20260904_060000_abcd",
                strategy_version="v2",
                query_manifest="queries.json",
                target_count=10,
                api_budget=100,
                partitions=[],
            )
            state["seen_source_ids"] = ["123"]
            bulk.queue_failure(
                state,
                source_document_id="123",
                partition_id="p1",
                stage="document",
                failure_type="network",
                retryable=True,
                error_code="temporary",
            )
            bulk.start_new_run(root, state)

            loaded = bulk.load_run_state(root, "bulk_20260904_060000_abcd")

            self.assertEqual(loaded["seen_source_ids"], ["123"])
            self.assertEqual(loaded["failed_queue"][0]["source_document_id"], "123")
            self.assertTrue(loaded["failed_queue"][0]["retryable"])

    def test_append_batch_and_statistics_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = bulk.create_run_state(
                "bulk_20260904_060000_abcd",
                strategy_version="v2",
                query_manifest="queries.json",
                target_count=10,
                api_budget=100,
                partitions=[{"partition_id": "p1", "status": "completed"}],
            )
            bulk.start_new_run(root, state)
            bulk.append_batch(root, state, [{"source_document_id": "1"}])
            bulk.save_run_state(root, state)

            stats = bulk.run_statistics(bulk.load_run_state(root, "bulk_20260904_060000_abcd"))

            self.assertEqual(stats["partitions"]["completed"], 1)
            self.assertEqual(stats["batches"][0]["path"], "batches/batch_0001.json")
            self.assertTrue((root / "bulk_20260904_060000_abcd/batches/batch_0001.json").exists())

    def test_rebuild_dedupe_index_from_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "records.json"
            output = root / "dedupe.json"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "local_id": "v2-1",
                            "source_provider": "indian_kanoon",
                            "source_document_id": "1",
                            "sha256": "abc",
                            "status": "validated",
                        },
                        {
                            "local_id": "v2-2",
                            "source_provider": "indian_kanoon",
                            "source_document_id": "2",
                            "sha256": "abc",
                            "status": "validated",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            index = bulk.rebuild_dedupe_index([manifest], output)

            self.assertEqual(len(index), 3)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
