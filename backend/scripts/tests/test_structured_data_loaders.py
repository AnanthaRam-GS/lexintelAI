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


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
