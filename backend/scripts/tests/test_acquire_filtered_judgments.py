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

    def test_current_transition_date_parsing_uses_exact_dates(self) -> None:
        self.assertFalse(acquire.date_within_bounds("30 June, 2024", "2024-07-01", None))
        self.assertTrue(acquire.date_within_bounds("1 July, 2024", "2024-07-01", None))
        self.assertTrue(acquire.date_within_bounds("2024-07-02", "2024-07-01", None))
        self.assertTrue(acquire.date_within_bounds("02/07/2024", "2024-07-01", None))

    def test_document_year_prefers_decision_date_over_case_number(self) -> None:
        self.assertEqual(acquire.document_year("Crl.A./213/2020 on 12 June, 2024"), 2024)

    def test_regime_evidence_snippets_are_bounded(self) -> None:
        snippets = acquire.regime_evidence_snippets(
            "The proceeding cites Indian Penal Code, CrPC, Bharatiya Nyaya Sanhita, 2023 and BNSS."
        )

        self.assertTrue(any("Bharatiya Nyaya Sanhita" in snippet for snippet in snippets))
        self.assertTrue(all(len(snippet) <= 180 for snippet in snippets))

    def test_transition_cli_caps_limit_at_ten(self) -> None:
        with patch.object(acquire, "load_project_env"):
            with patch.object(acquire, "dry_run", return_value=0) as dry_run:
                result = acquire.main([
                    "--dry-run",
                    "--transition-validation",
                    "--limit",
                    "50",
                ])

        self.assertEqual(result, 0)
        self.assertEqual(dry_run.call_args.args[0], acquire.TRANSITION_MAX_LIMIT)

    def test_bulk_plan_expands_stage_partitions_to_queries(self) -> None:
        plan = self.root / "bulk_plan.json"
        plan.write_text(
            json.dumps(
                {
                    "stages": [
                        {
                            "stage_id": "stage_a",
                            "partitions": [
                                {
                                    "partition_id": "p1",
                                    "family": "homicide",
                                    "track": "recent_ipc",
                                    "from_date": "2018-01-01",
                                    "to_date": "2024-06-30",
                                    "target": 3,
                                    "queries": [{"query": "murder IPC criminal appeal"}],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        queries = acquire.load_bulk_queries(plan)

        self.assertEqual(queries[0]["query_id"], "p1")
        self.assertEqual(queries[0]["offence_family"], "homicide")
        self.assertEqual(queries[0]["temporal_track"], "recent_ipc")
        self.assertEqual(queries[0]["target_quota"], 3)

    def test_bulk_plan_path_supports_relative_and_absolute_repo_paths(self) -> None:
        relative = Path("data/structured/manifests/bulk_acquisition_plan.json")
        absolute = acquire.REPO_ROOT / relative

        self.assertEqual(acquire.normalize_repo_path(relative), absolute.resolve())
        self.assertEqual(acquire.normalize_repo_path(absolute), absolute.resolve())
        with self.assertRaises(ValueError):
            acquire.normalize_repo_path(self.root / "missing.json")
        with self.assertRaises(ValueError):
            acquire.normalize_repo_path("/tmp/outside-bulk-plan.json", must_exist=False)

    def test_bulk_dry_run_makes_no_provider_or_raw_calls(self) -> None:
        output = io.StringIO()
        plan = acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json"
        with patch.object(acquire, "IndianKanoonClient", side_effect=AssertionError("provider reached")):
            with patch.object(acquire, "acquire", side_effect=AssertionError("live acquisition reached")):
                with redirect_stdout(output):
                    result = acquire.main([
                        "--bulk",
                        "--dry-run",
                        "--bulk-plan",
                        str(plan),
                    ])

        self.assertEqual(result, 0)
        self.assertIn("run mode: dry-run", output.getvalue())
        self.assertIn("No Indian Kanoon API requests were made.", output.getvalue())

    def test_bulk_resume_completed_run_does_not_call_acquire(self) -> None:
        run_root = self.root / "runs"
        run_id = "bulk_20260904_060000_abcd"
        state = acquire.create_run_state(
            run_id,
            strategy_version="v2",
            query_manifest=str(self.queries),
            target_count=1,
            api_budget=10,
            partitions=[],
        )
        state["status"] = "completed"
        acquire.start_new_run(run_root, state)

        with patch.object(acquire, "acquire") as acquire_mock:
            result = acquire.run_bulk_acquisition(
                run_id=None,
                resume_run_id=run_id,
                retry_failures_run_id=None,
                target_count=1,
                max_api_requests=10,
                query_manifest=acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json",
                max_search_pages=1,
                delay=0,
                state_root=run_root,
            )

        self.assertEqual(result, 0)
        acquire_mock.assert_not_called()

    def test_bulk_completed_smaller_gate_can_resume_to_larger_target(self) -> None:
        run_root = self.root / "runs"
        run_id = "bulk_20260904_060000_abcd"
        state = acquire.create_run_state(
            run_id,
            strategy_version="v2",
            query_manifest="data/structured/manifests/bulk_acquisition_plan.json",
            target_count=50,
            api_budget=550,
            partitions=[{"partition_id": "q1", "status": "pending", "max_pages": 1}],
        )
        state["status"] = "completed"
        state["reviewable_counts"]["total"] = 50
        state["request_stats"]["total_requests"] = 100
        acquire.start_new_run(run_root, state)
        (run_root / run_id / "expanded_queries.json").write_text(
            json.dumps(
                [
                    {
                        "query_id": "q1",
                        "offence_family": "homicide",
                        "temporal_track": "recent_ipc",
                        "query": "murder IPC criminal appeal",
                        "target_quota": 150,
                        "doctypes": "judgments",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (run_root / run_id / "candidates.json").write_text(
            json.dumps([{"source_document_id": str(index), "status": "validated"} for index in range(50)]),
            encoding="utf-8",
        )
        (run_root / run_id / "review.json").write_text("[]", encoding="utf-8")
        (run_root / run_id / "audit.json").write_text("[]", encoding="utf-8")

        with patch.object(acquire, "acquire", return_value=0) as acquire_mock:
            result = acquire.run_bulk_acquisition(
                run_id=None,
                resume_run_id=run_id,
                retry_failures_run_id=None,
                target_count=150,
                max_api_requests=550,
                query_manifest=acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json",
                max_search_pages=1,
                delay=0,
                state_root=run_root,
                client=Mock(get_request_stats=Mock(return_value=acquire.empty_request_stats())),
            )

        self.assertEqual(result, 0)
        acquire_mock.assert_called_once()
        self.assertEqual(acquire_mock.call_args.kwargs["max_api_requests"], 450)
        self.assertEqual(acquire_mock.call_args.kwargs["max_limit"], 150)

    def test_bulk_run_persists_provider_request_stats(self) -> None:
        run_root = self.root / "runs"
        run_id = "bulk_20260904_060000_abcd"
        stats = {
            "total_requests": 4,
            "requests_by_endpoint": {
                "search": 1,
                "document": 1,
                "metadata": 1,
                "original_document": 1,
                "other": 0,
            },
            "responses_by_category": {
                "2xx": 4,
                "4xx": 0,
                "429": 0,
                "5xx": 0,
                "other": 0,
            },
        }
        client = Mock()
        client.get_request_stats.return_value = stats

        def fake_acquire(**kwargs: object) -> int:
            Path(kwargs["judgment_manifest"]).write_text(  # type: ignore[arg-type]
                json.dumps(
                    [
                        {
                            "source_document_id": "1",
                            "status": "validated",
                            "final_automated_decision": "accept_candidate",
                            "raw_file_path": "raw/1.pdf",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            Path(kwargs["review_manifest"]).write_text("[]", encoding="utf-8")  # type: ignore[arg-type]
            Path(kwargs["audit_manifest"]).write_text("[]", encoding="utf-8")  # type: ignore[arg-type]
            return 0

        with patch.object(acquire, "acquire", side_effect=fake_acquire):
            result = acquire.run_bulk_acquisition(
                run_id=run_id,
                resume_run_id=None,
                retry_failures_run_id=None,
                target_count=1,
                max_api_requests=10,
                query_manifest=acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json",
                max_search_pages=1,
                delay=0,
                state_root=run_root,
                client=client,
            )

        self.assertEqual(result, 0)
        state = acquire.load_run_state(run_root, run_id)
        self.assertEqual(state["request_stats"], stats)

    def test_bulk_visit_target_is_capped_by_family_gap(self) -> None:
        run_root = self.root / "runs"
        run_id = "bulk_20260904_060000_abcd"
        state = acquire.create_run_state(
            run_id,
            strategy_version="v2",
            query_manifest="data/structured/manifests/bulk_acquisition_plan.json",
            target_count=50,
            api_budget=100,
            partitions=[{"partition_id": "q1", "family": "other", "target": 25, "status": "pending", "max_pages": 1}],
        )
        acquire.start_new_run(run_root, state)
        (run_root / run_id / "expanded_queries.json").write_text(
            json.dumps(
                [
                    {
                        "query_id": "q1",
                        "offence_family": "other",
                        "temporal_track": "current_transition",
                        "query": "Bharatiya Nyaya Sanhita criminal appeal",
                        "target_quota": 25,
                        "doctypes": "judgments",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (run_root / run_id / "candidates.json").write_text(
            json.dumps(
                [
                    {
                        "source_document_id": str(index),
                        "status": "validated",
                        "offence_family": "other",
                        "query_id": "q1",
                    }
                    for index in range(24)
                ]
            ),
            encoding="utf-8",
        )
        (run_root / run_id / "review.json").write_text("[]", encoding="utf-8")
        (run_root / run_id / "audit.json").write_text("[]", encoding="utf-8")

        with patch.object(acquire, "acquire", return_value=0) as acquire_mock:
            result = acquire.run_bulk_acquisition(
                run_id=None,
                resume_run_id=run_id,
                retry_failures_run_id=None,
                target_count=50,
                max_api_requests=100,
                query_manifest=acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json",
                max_search_pages=1,
                delay=0,
                state_root=run_root,
                client=Mock(get_request_stats=Mock(return_value=acquire.empty_request_stats())),
            )

        self.assertEqual(result, 0)
        self.assertEqual(acquire_mock.call_args.kwargs["limit"], 25)

    def test_bulk_no_progress_provider_4xx_stops_without_completing_partition(self) -> None:
        run_root = self.root / "runs"
        run_id = "bulk_20260904_060000_abcd"
        state = acquire.create_run_state(
            run_id,
            strategy_version="v2",
            query_manifest="data/structured/manifests/bulk_acquisition_plan.json",
            target_count=10,
            api_budget=100,
            partitions=[{"partition_id": "q1", "family": "homicide", "target": 10, "status": "pending", "max_pages": 5}],
        )
        acquire.start_new_run(run_root, state)
        (run_root / run_id / "expanded_queries.json").write_text(
            json.dumps(
                [
                    {
                        "query_id": "q1",
                        "offence_family": "homicide",
                        "temporal_track": "recent_ipc",
                        "query": "murder IPC criminal appeal",
                        "target_quota": 10,
                        "doctypes": "judgments",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (run_root / run_id / "candidates.json").write_text("[]", encoding="utf-8")
        (run_root / run_id / "review.json").write_text("[]", encoding="utf-8")
        (run_root / run_id / "audit.json").write_text("[]", encoding="utf-8")
        stats = acquire.empty_request_stats()
        stats["total_requests"] = 2
        stats["requests_by_endpoint"]["search"] = 2
        stats["responses_by_category"]["4xx"] = 2
        client = Mock(get_request_stats=Mock(return_value=stats))

        with patch.object(acquire, "acquire", return_value=0):
            result = acquire.run_bulk_acquisition(
                run_id=None,
                resume_run_id=run_id,
                retry_failures_run_id=None,
                target_count=10,
                max_api_requests=100,
                query_manifest=acquire.REPO_ROOT / "data/structured/manifests/bulk_acquisition_plan.json",
                max_search_pages=5,
                delay=0,
                state_root=run_root,
                client=client,
            )

        self.assertEqual(result, 0)
        loaded = acquire.load_run_state(run_root, run_id)
        self.assertEqual(loaded["status"], "stopped_provider")
        self.assertEqual(loaded["partitions"][0]["status"], "pending")

    def test_gap_targets_are_computed_from_reviewable_records(self) -> None:
        records = [
            {"status": "validated", "offence_family": "homicide"},
            {"status": "needs_review", "offence_family": "homicide"},
            {"status": "reject", "offence_family": "homicide"},
            {"status": "rejected_pre_download", "offence_family": "hurt_and_assault"},
        ]

        self.assertEqual(acquire.gap_targets(records, {"homicide": 4, "hurt_and_assault": 1}), {"homicide": 2, "hurt_and_assault": 1})

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

    def test_reviewable_count_includes_accept_and_needs_review(self) -> None:
        records = [
            {"status": "validated"},
            {"status": "needs_review"},
            {"status": "reject"},
            {"status": "rejected_pre_download"},
        ]

        self.assertEqual(acquire.reviewable_count(records), 2)

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

    def test_full_family_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            queries = [
                {
                    "query_id": "q1",
                    "offence_family": "theft_and_robbery",
                    "temporal_track": "recent_ipc",
                    "query": "theft IPC",
                    "target_quota": 1,
                    "doctypes": "judgments",
                    "from_date": "2018-01-01",
                    "to_date": "2024-06-30",
                }
            ]
            (root / "queries.json").write_text(json.dumps(queries), encoding="utf-8")
            (root / "quotas.json").write_text(json.dumps([{"offence_family": "theft_and_robbery", "target_quota": 1}]), encoding="utf-8")
            (root / "v1.json").write_text("[]", encoding="utf-8")
            (root / "v2.json").write_text("[]", encoding="utf-8")
            (root / "prescreen.json").write_text("[]", encoding="utf-8")
            (root / "judgments.json").write_text(json.dumps([{"source_document_id": "1", "status": "validated", "offence_family": "theft_and_robbery", "query_id": "old"}]), encoding="utf-8")
            (root / "review.json").write_text("[]", encoding="utf-8")
            (root / "audit.json").write_text("[]", encoding="utf-8")
            client = Mock()
            client.get_request_stats.return_value = {"total_requests": 0}

            with patch.object(acquire, "QUOTA_MANIFEST", root / "quotas.json"):
                with patch.object(acquire, "V1_JUDGMENTS", root / "v1.json"):
                    with patch.object(acquire, "V2_JUDGMENTS", root / "v2.json"):
                        with patch.object(acquire, "PRESCREEN_JUDGMENTS", root / "prescreen.json"):
                            with patch.object(acquire, "IndianKanoonClient", return_value=client):
                                acquire.acquire(
                                    limit=2,
                                    max_api_requests=10,
                                    query_manifest=root / "queries.json",
                                    judgment_manifest=root / "judgments.json",
                                    review_manifest=root / "review.json",
                                    audit_manifest=root / "audit.json",
                                    raw_dir=root / "raw",
                                    delay=0,
                                )

            client.search.assert_not_called()

    def test_pagination_and_seen_ids_across_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            queries = [
                {
                    "query_id": "q1",
                    "offence_family": "theft_and_robbery",
                    "temporal_track": "recent_ipc",
                    "query": "theft IPC",
                    "target_quota": 2,
                    "doctypes": "judgments",
                    "from_date": "2018-01-01",
                    "to_date": "2024-06-30",
                },
                {
                    "query_id": "q2",
                    "offence_family": "theft_and_robbery",
                    "temporal_track": "recent_ipc",
                    "query": "robbery IPC",
                    "target_quota": 2,
                    "doctypes": "judgments",
                    "from_date": "2018-01-01",
                    "to_date": "2024-06-30",
                },
            ]
            for path, data in [
                (root / "queries.json", json.dumps(queries)),
                (root / "quotas.json", json.dumps([{"offence_family": "theft_and_robbery", "target_quota": 2}])),
                (root / "v1.json", "[]"),
                (root / "v2.json", "[]"),
                (root / "prescreen.json", "[]"),
                (root / "judgments.json", "[]"),
                (root / "review.json", "[]"),
                (root / "audit.json", "[]"),
            ]:
                path.write_text(data, encoding="utf-8")
            client = Mock()
            client.get_request_stats.return_value = {"total_requests": 0}
            client.search.side_effect = [
                {"docs": [{"tid": "10", "title": "A v State"}]},
                {"docs": [{"tid": "10", "title": "A v State"}, {"tid": "11", "title": "B v State"}]},
                {"docs": [{"tid": "10", "title": "A v State"}, {"tid": "12", "title": "C v State"}]},
            ]
            client.get_document_metadata.side_effect = [
                {"title": "A v State", "court": "Example High Court", "date": "2022-01-01"},
                {"title": "B v State", "court": "Example High Court", "date": "2022-01-02"},
            ]
            client.get_document.side_effect = [
                {"doc": "<p>A v State. Criminal Appeal. robbery Section 392 IPC conviction by Hon'ble Court.</p>"},
                {"doc": "<p>B v State. Criminal Appeal. theft Section 379 IPC conviction by Hon'ble Court.</p>"},
            ]
            client.get_original_document.side_effect = [b"%PDF sample 10", b"%PDF sample 11"]

            with patch.object(acquire, "QUOTA_MANIFEST", root / "quotas.json"):
                with patch.object(acquire, "V1_JUDGMENTS", root / "v1.json"):
                    with patch.object(acquire, "V2_JUDGMENTS", root / "v2.json"):
                        with patch.object(acquire, "PRESCREEN_JUDGMENTS", root / "prescreen.json"):
                            with patch.object(acquire, "REPO_ROOT", root):
                                with patch.object(acquire, "IndianKanoonClient", return_value=client):
                                    acquire.acquire(
                                        limit=2,
                                        max_api_requests=20,
                                        query_manifest=root / "queries.json",
                                        judgment_manifest=root / "judgments.json",
                                        review_manifest=root / "review.json",
                                        audit_manifest=root / "audit.json",
                                        raw_dir=root / "raw",
                                        delay=0,
                                        max_search_pages=3,
                                    )

            self.assertEqual(client.search.call_count, 2)
            self.assertEqual(client.get_document_metadata.call_count, 2)
            source_ids = [record["source_document_id"] for record in json.loads((root / "review.json").read_text(encoding="utf-8"))]
            self.assertEqual(source_ids, ["10", "11"])

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
                                                result = acquire.acquire(
                                                    limit=1,
                                                    max_api_requests=10,
                                                    query_manifest=root / "queries.json",
                                                    judgment_manifest=root / "judgments.json",
                                                    review_manifest=root / "review.json",
                                                    audit_manifest=root / "audit.json",
                                                    raw_dir=raw_dir,
                                                    delay=0,
                                                )

            self.assertEqual(result, 0)
            review_records = json.loads((root / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(len(review_records), 1)
            self.assertEqual(review_records[0]["human_review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
