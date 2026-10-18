"""Tests for LegalAI Task 1.R.3 IPC-BNS and NCRB database loaders."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.db.models import IpcBnsMapping, NcrbStat
from backend.app.db.session import SessionLocal
from backend.scripts.load_ipc_bns import DEFAULT_CSV_PATH as IPC_CSV
from backend.scripts.load_ipc_bns import load_ipc_bns_mapping
from backend.scripts.load_ncrb import DEFAULT_CSV_PATH as NCRB_CSV
from backend.scripts.load_ncrb import load_ncrb_stats

MARKER = "R3_LOADER_TEST"


class TestStructuredDataLoaders(unittest.TestCase):
    """Idempotency, validation, and project-dataset compatibility tests."""

    def setUp(self) -> None:
        self.db = SessionLocal()
        self._cleanup()

    def tearDown(self) -> None:
        self._cleanup()
        self.db.close()

    def _cleanup(self) -> None:
        self.db.query(IpcBnsMapping).filter(IpcBnsMapping.ipc_section.like(f"{MARKER}%")).delete(
            synchronize_session=False
        )
        self.db.query(NcrbStat).filter(NcrbStat.state.like(f"{MARKER}%")).delete(
            synchronize_session=False
        )
        self.db.commit()

    def test_default_dataset_paths_and_headers_exist(self) -> None:
        self.assertTrue(IPC_CSV.exists())
        self.assertTrue(NCRB_CSV.exists())
        with IPC_CSV.open(encoding="utf-8-sig", newline="") as handle:
            ipc_headers = set(csv.DictReader(handle).fieldnames or [])
        with NCRB_CSV.open(encoding="utf-8-sig", newline="") as handle:
            ncrb_headers = set(csv.DictReader(handle).fieldnames or [])
        self.assertTrue(
            {
                "ipc_section",
                "ipc_description",
                "bns_section",
                "bns_description",
                "change_type",
            }.issubset(ipc_headers)
        )
        self.assertTrue(
            {
                "year",
                "state",
                "offense_category",
                "ipc_section",
                "case_count",
                "conviction_count",
                "acquittal_count",
            }.issubset(ncrb_headers)
        )

    def test_ipc_bns_loader_is_idempotent(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["ipc_section", "ipc_description", "bns_section", "bns_description", "change_type"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "ipc_section": f"{MARKER}-302",
                    "ipc_description": "Test murder",
                    "bns_section": "101",
                    "bns_description": "Test BNS",
                    "change_type": "DIRECT",
                }
            )
            writer.writerow(
                {
                    "ipc_section": "",
                    "ipc_description": "invalid",
                    "bns_section": "",
                    "bns_description": "",
                    "change_type": "DIRECT",
                }
            )
            csv_path = Path(handle.name)

        try:
            first = load_ipc_bns_mapping(self.db, csv_path)
            second = load_ipc_bns_mapping(self.db, csv_path)
        finally:
            csv_path.unlink(missing_ok=True)

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["skipped_invalid"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["skipped_existing"], 1)
        count = (
            self.db.query(IpcBnsMapping)
            .filter(IpcBnsMapping.ipc_section == f"{MARKER}-302")
            .count()
        )
        self.assertEqual(count, 1)

    def test_ncrb_loader_skips_duplicates_and_maps_complete_schema(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "year",
                    "state",
                    "offense_category",
                    "ipc_section",
                    "bns_section",
                    "case_count",
                    "conviction_count",
                    "acquittal_count",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "year": "2024",
                    "state": f"{MARKER} State",
                    "offense_category": "Murder",
                    "ipc_section": "302",
                    "bns_section": "101",
                    "case_count": "9",
                    "conviction_count": "",
                    "acquittal_count": "",
                }
            )
            writer.writerow(
                {
                    "year": "2024",
                    "state": f"{MARKER} State",
                    "offense_category": "Murder",
                    "ipc_section": "302",
                    "bns_section": "101",
                    "case_count": "9",
                    "conviction_count": "",
                    "acquittal_count": "",
                }
            )
            csv_path = Path(handle.name)

        try:
            first = load_ncrb_stats(self.db, csv_path)
            second = load_ncrb_stats(self.db, csv_path)
        finally:
            csv_path.unlink(missing_ok=True)

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["skipped_existing"], 1)
        self.assertEqual(second["inserted"], 0)
        row = (
            self.db.query(NcrbStat)
            .filter(NcrbStat.state == f"{MARKER} State")
            .one()
        )
        self.assertEqual(row.case_count, 9)
        self.assertIsNone(row.conviction_count)
        self.assertEqual(row.ipc_section, "302")
        self.assertNotIn("bns_section", NcrbStat.__table__.c)

    def test_real_datasets_dry_run_without_inserting_duplicates(self) -> None:
        ipc_stats = load_ipc_bns_mapping(self.db, IPC_CSV, dry_run=True)
        ncrb_stats = load_ncrb_stats(self.db, NCRB_CSV, dry_run=True)
        self.assertGreater(ipc_stats["source_rows"], 0)
        self.assertGreater(ncrb_stats["source_rows"], 0)
        self.assertEqual(ipc_stats["inserted"], 0)
        self.assertEqual(ncrb_stats["inserted"], 0)
        self.assertEqual(ipc_stats["skipped_invalid"], 0)
        self.assertEqual(ncrb_stats["skipped_invalid"], 0)


NCRB_FIELDS = ["year", "state", "offense_category", "ipc_section", "bns_section", "case_count", "conviction_count", "acquittal_count"]
IPC_FIELDS = ["ipc_section", "ipc_description", "bns_section", "bns_description", "change_type"]


def write_csv(fieldnames: list[str], rows: list[dict]) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return Path(handle.name)


def ncrb_row(**overrides) -> dict:
    row = {"year": "2024", "state": f"{MARKER} State", "offense_category": "Murder", "ipc_section": "302",
           "bns_section": "103", "case_count": "9", "conviction_count": "", "acquittal_count": ""}
    row.update(overrides)
    return row


class TestLoaderValidation(unittest.TestCase):
    """Rejection reasons, NULL handling and idempotent upserts."""

    def setUp(self) -> None:
        self.db = SessionLocal()
        self.paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self.paths:
            path.unlink(missing_ok=True)
        self.db.close()

    def csv(self, fieldnames: list[str], rows: list[dict]) -> Path:
        path = write_csv(fieldnames, rows)
        self.paths.append(path)
        return path

    def test_ncrb_rejections_are_counted_by_reason_and_missing_counts_stay_null(self) -> None:
        path = self.csv(NCRB_FIELDS, [
            ncrb_row(),
            ncrb_row(offense_category="Not reported", case_count=""),
            ncrb_row(offense_category="Non integer", case_count="12a"),
            ncrb_row(offense_category="Negative", case_count="-3"),
            ncrb_row(offense_category="", ipc_section="999"),
            ncrb_row(case_count="10"),  # same key as the first row, different count
            ncrb_row(),  # exact repeat of the first row
            ncrb_row(offense_category="Hyphen suffix", ipc_section="366-B", bns_section=""),
        ])
        stats = load_ncrb_stats(self.db, path)
        self.assertEqual(stats["rejected"], {
            "duplicate_key_conflict": 1, "missing_required_field": 1, "negative_count": 1, "non_integer_value": 1,
        })
        self.assertEqual(stats["inserted"], 3)
        self.assertEqual(stats["skipped_existing"], 1)
        self.assertEqual(stats["notes"]["exact_duplicate_in_file"], 1)
        self.assertEqual(stats["notes"]["case_count_not_reported"], 1)
        self.assertEqual(stats["notes"]["bns_section_not_stored"], 2)
        self.assertEqual(stats["source_rows"], stats["inserted"] + stats["skipped_existing"] + stats["skipped_invalid"])

        not_reported = self.db.query(NcrbStat).filter_by(offense_category="Not reported").one()
        self.assertIsNone(not_reported.case_count)  # never fabricated as 0
        self.assertEqual(self.db.query(NcrbStat).filter_by(offense_category="Hyphen suffix").one().ipc_section, "366B")

    def test_ncrb_upsert_updates_changed_counts_then_makes_no_changes(self) -> None:
        load_ncrb_stats(self.db, self.csv(NCRB_FIELDS, [ncrb_row()]))
        changed = load_ncrb_stats(self.db, self.csv(NCRB_FIELDS, [ncrb_row(case_count="11")]))
        self.assertEqual((changed["inserted"], changed["updated"]), (0, 1))
        again = load_ncrb_stats(self.db, self.paths[-1])
        self.assertEqual((again["inserted"], again["updated"], again["skipped_existing"]), (0, 0, 1))
        self.assertEqual(self.db.query(NcrbStat).filter_by(state=f"{MARKER} State").one().case_count, 11)

    def test_ipc_bns_rejections_are_counted_by_reason(self) -> None:
        good = {"ipc_section": f"{MARKER}-498-A", "ipc_description": "Cruelty", "bns_section": "85", "bns_description": "Cruelty", "change_type": "direct"}
        path = self.csv(IPC_FIELDS, [
            good,
            dict(good),  # exact repeat
            {**good, "ipc_description": ""},
            {**good, "ipc_description": "Other", "change_type": "RENUMBERED"},
            {**good, "ipc_description": "Too long", "bns_section": "1" * 60},
        ])
        stats = load_ipc_bns_mapping(self.db, path)
        self.assertEqual(stats["rejected"], {"field_too_long": 1, "invalid_change_type": 1, "missing_required_field": 1})
        self.assertEqual((stats["inserted"], stats["exact_duplicate_in_file"]), (1, 1))
        row = self.db.query(IpcBnsMapping).filter(IpcBnsMapping.ipc_section.like(f"{MARKER}%")).one()
        self.assertEqual((row.ipc_section, row.change_type), (f"{MARKER}-498A", "DIRECT"))
        self.assertEqual(load_ipc_bns_mapping(self.db, path)["inserted"], 0)


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
