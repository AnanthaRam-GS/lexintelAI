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
            review = root / "review.json"
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
                            "local_id": "v2-1-copy",
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
            review.write_text(
                json.dumps(
                    [
                        {
                            "source_document_id": "1",
                            "human_review_status": "rejected",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            index = bulk.rebuild_dedupe_index([manifest], output, [review])

            self.assertEqual(len(index["source_key_index"]), 2)
            self.assertEqual(index["source_key_index"]["indian_kanoon:1"]["canonical_status"], "human_rejected")
            self.assertEqual(index["sha_index"]["abc"]["alias_count"], 2)
            self.assertTrue(output.exists())

    def test_interrupted_resume_simulation_matches_uninterrupted_run(self) -> None:
        candidates = [
            {
                "local_id": f"v2-{index}",
                "source_provider": "indian_kanoon",
                "source_document_id": str(index),
                "sha256": f"sha-{index // 2}" if index in {80, 81} else f"sha-{index}",
                "status": "validated" if index % 5 else "rejected_pre_download",
                "final_automated_decision": "reject" if index % 5 == 0 else "accept_candidate",
                "raw_file_path": f"raw/{index}.pdf" if index % 5 else None,
            }
            for index in range(1, 121)
        ]

        def run(root: Path, run_id: str, interrupt_after: int | None = None) -> dict[str, object]:
            state = bulk.create_run_state(
                run_id,
                strategy_version="v2",
                query_manifest="synthetic.json",
                target_count=120,
                api_budget=1000,
                partitions=[{"partition_id": "p1", "status": "running"}],
                batch_size=50,
            )
            bulk.start_new_run(root, state)
            processed: list[dict[str, object]] = []
            for index, record in enumerate(candidates, start=1):
                processed.append(record)
                bulk.append_unique(state, "seen_source_ids", str(record["source_document_id"]))
                state["request_stats"]["total_requests"] += 1
                if len(processed) % 50 == 0:
                    bulk.append_batch(root, state, processed[-50:])
                if interrupt_after and index == interrupt_after:
                    state["status"] = "paused"
                    bulk.queue_failure(
                        state,
                        source_document_id="temporary-network",
                        partition_id="p1",
                        stage="document",
                        failure_type="network",
                        retryable=True,
                    )
                    bulk.save_run_state(root, state)
                    state = bulk.load_run_state(root, run_id)
            remainder = len(processed) % 50
            if remainder:
                bulk.append_batch(root, state, processed[-remainder:])
            state["status"] = "completed"
            state["candidate_counts"] = {
                "seen": len(processed),
                "processed": len(processed),
                "downloaded": sum(1 for item in processed if item.get("raw_file_path")),
                "duplicates": 0,
                "rejected": sum(1 for item in processed if item.get("final_automated_decision") == "reject"),
            }
            state["reviewable_counts"] = {
                "total": sum(1 for item in processed if item.get("final_automated_decision") in {"accept_candidate", "needs_review"}),
                "accept_candidate": sum(1 for item in processed if item.get("final_automated_decision") == "accept_candidate"),
                "needs_review": 0,
            }
            state["partitions"][0]["status"] = "completed"
            bulk.save_run_state(root, state)
            manifest = root / f"{run_id}.json"
            manifest.write_text(json.dumps(processed), encoding="utf-8")
            dedupe = bulk.rebuild_dedupe_index([manifest], root / f"{run_id}-dedupe.json")
            stats = bulk.run_statistics(bulk.load_run_state(root, run_id))
            return {"stats": stats, "dedupe": dedupe}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uninterrupted = run(root, "bulk_20260904_060000_aaaa")
            resumed = run(root, "bulk_20260904_060000_bbbb", interrupt_after=50)

            self.assertEqual(uninterrupted["stats"]["processed_candidates"], resumed["stats"]["processed_candidates"])
            self.assertEqual(uninterrupted["stats"]["request_stats"]["total_requests"], resumed["stats"]["request_stats"]["total_requests"])
            self.assertEqual(
                set(uninterrupted["dedupe"]["source_key_index"]),
                set(resumed["dedupe"]["source_key_index"]),
            )
            self.assertEqual(uninterrupted["dedupe"]["sha_index"], resumed["dedupe"]["sha_index"])
            self.assertEqual(resumed["stats"]["batches"][-1]["record_count"], 20)

    def test_budget_stop_requires_explicit_resume_and_preserves_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "bulk_20260904_060000_cccc"
            state = bulk.create_run_state(
                run_id,
                strategy_version="v2",
                query_manifest="synthetic.json",
                target_count=10,
                api_budget=3,
                partitions=[{"partition_id": "p1", "status": "running"}],
            )
            bulk.start_new_run(root, state)
            state["request_stats"]["total_requests"] = 3
            state["status"] = "stopped_budget"
            bulk.save_run_state(root, state)

            loaded = bulk.load_run_state(root, run_id)

            self.assertEqual(loaded["status"], "stopped_budget")
            self.assertEqual(loaded["request_stats"]["total_requests"], 3)


if __name__ == "__main__":
    unittest.main()
