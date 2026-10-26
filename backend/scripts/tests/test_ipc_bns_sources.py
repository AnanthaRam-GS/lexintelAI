"""Source-attributed IPC-BNS mapping (migration 0011, step 19b): constraints, loads, collisions, API, migration."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.db.models import IpcBnsMapping
from backend.app.db.session import SessionLocal, engine
from backend.main import app
from backend.scripts.load_ipc_bns import CYTRAIN, NCRB_CSV_PATH, NCRB_T1A4, load_ipc_bns_mapping

NAMED_PAIRS = {  # step 15b's seven printed pairs: (printed IPC group, BNS section) -> table page
    ("379-382", "303"): 52, ("384-389", "308"): 57, ("392/394/397", "309"): 57, ("396", "310"): 59,
    ("406-409", "316"): 61, ("411-414", "317"): 61, ("153A", "196"): 50,
}
CANDIDATE_FIELDS = ("ipc_section", "ipc_description", "bns_section", "bns_description", "change_type", "source", "source_page", "pdf_page")


def alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=REPO_ROOT, env={**os.environ}, capture_output=True, text=True)


class MappingSourceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        self.addCleanup(self.db.close)

    def write_csv(self, rows: list[dict]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in CANDIDATE_FIELDS} for row in rows])
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return Path(handle.name)


class ConstraintTests(MappingSourceTestCase):
    def insert(self, **values) -> None:
        self.db.add(IpcBnsMapping(ipc_section="302", ipc_description="Murder", bns_section="103", **values))
        self.db.commit()

    def test_a_cytrain_row_needs_a_change_type(self) -> None:
        with self.assertRaises(IntegrityError) as caught:
            self.insert(source=CYTRAIN, change_type=None)
        self.assertIn("ck_ipc_bns_mapping_change_type_source", str(caught.exception))
        self.db.rollback()

    def test_an_ncrb_row_may_leave_it_null_and_an_unknown_source_is_refused(self) -> None:
        self.insert(source=NCRB_T1A4, change_type=None, source_page=50)
        self.assertEqual(self.db.query(IpcBnsMapping).one().change_type, None)
        with self.assertRaises(IntegrityError) as caught:
            self.insert(source="WIKIPEDIA", change_type="DIRECT")
        self.assertIn("ck_ipc_bns_mapping_source", str(caught.exception))
        self.db.rollback()


class LoaderTests(MappingSourceTestCase):
    def test_the_project_files_load_370_cytrain_and_68_ncrb_rows_idempotently(self) -> None:
        cytrain = load_ipc_bns_mapping(self.db)
        ncrb_dry = load_ipc_bns_mapping(self.db, source=NCRB_T1A4, dry_run=True)
        ncrb = load_ipc_bns_mapping(self.db, source=NCRB_T1A4)
        self.assertEqual((cytrain["inserted"], ncrb_dry["would_insert"], ncrb_dry["inserted"], ncrb["inserted"]), (370, 68, 0, 68))
        self.assertEqual((ncrb["collisions"], ncrb["skipped_invalid"], ncrb["exact_duplicate_in_file"]), ([], 0, 0))
        again = [load_ipc_bns_mapping(self.db), load_ipc_bns_mapping(self.db, source=NCRB_T1A4)]
        self.assertEqual([stats["inserted"] for stats in again], [0, 0])
        counts = dict(self.db.execute(text("SELECT source, count(*) FROM ipc_bns_mapping GROUP BY source")).all())
        self.assertEqual(counts, {CYTRAIN: 370, NCRB_T1A4: 68})
        nulls = self.db.execute(text("SELECT source, count(*) FROM ipc_bns_mapping WHERE change_type IS NULL GROUP BY source")).all()
        self.assertEqual(dict(nulls), {NCRB_T1A4: 68})  # every PDF row, and no CYTRAIN row
        for (ipc, bns), page in NAMED_PAIRS.items():
            with self.subTest(pair=(ipc, bns)):
                rows = self.db.query(IpcBnsMapping).filter_by(source=NCRB_T1A4, ipc_section=ipc, bns_section=bns).all()
                self.assertTrue(rows)
                self.assertEqual({row.source_page for row in rows}, {page})

    def test_a_collision_with_a_cytrain_row_is_reported_and_skipped(self) -> None:
        load_ipc_bns_mapping(self.db)
        existing = self.db.query(IpcBnsMapping).filter_by(source=CYTRAIN, ipc_section="302").first()
        before = (existing.ipc_description, existing.bns_description, existing.change_type, existing.source_page)
        path = self.write_csv([
            {"ipc_section": "302", "ipc_description": "Murder (printed head)", "bns_section": existing.bns_section,
             "bns_description": "Murder (printed head)", "source_page": "47"},
            {"ipc_section": "153A", "ipc_description": "Promoting enmity (printed head)", "bns_section": "196",
             "bns_description": "Promoting enmity (printed head)", "source_page": "50"},
        ])
        stats = load_ipc_bns_mapping(self.db, path, source=NCRB_T1A4)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["collisions"], [f"302 -> {existing.bns_section} (exists as CYTRAIN)"])
        self.db.refresh(existing)
        self.assertEqual((existing.ipc_description, existing.bns_description, existing.change_type, existing.source_page), before)
        self.assertEqual(self.db.query(IpcBnsMapping).filter_by(ipc_section="302", bns_section=existing.bns_section).count(), 1)

    def test_an_ncrb_row_needs_its_page_and_never_gets_a_guessed_change_type(self) -> None:
        path = self.write_csv([
            {"ipc_section": "396", "ipc_description": "Dacoity with Murder", "bns_section": "310", "bns_description": "Dacoity with Murder"},
            {"ipc_section": "411-414", "ipc_description": "Stolen Property", "bns_section": "317", "bns_description": "Stolen Property", "source_page": "61"},
        ])
        stats = load_ipc_bns_mapping(self.db, path, source=NCRB_T1A4)
        self.assertEqual((stats["inserted"], stats["rejected"]), (1, {"missing_source_page": 1}))
        row = self.db.query(IpcBnsMapping).filter_by(source=NCRB_T1A4).one()
        self.assertEqual((row.change_type, row.source_page), (None, 61))


class ApiTests(MappingSourceTestCase):
    def setUp(self) -> None:
        super().setUp()
        load_ipc_bns_mapping(self.db)
        load_ipc_bns_mapping(self.db, source=NCRB_T1A4)
        app.dependency_overrides[require_lawyer_or_admin] = lambda: type("U", (), {"id": 0, "role": "lawyer"})()
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_rows_carry_their_source_and_page_and_null_change_types(self) -> None:
        rows = self.client.get("/analytics/ipc-bns-map").json()
        self.assertEqual(len(rows), 438)
        self.assertEqual({row["source"] for row in rows}, {CYTRAIN, NCRB_T1A4})
        enmity = [row for row in rows if (row["ipc_section"], row["bns_section"]) == ("153A", "196")]
        self.assertEqual([(row["source"], row["source_page"], row["change_type"]) for row in enmity], [(NCRB_T1A4, 50, None)])
        self.assertTrue(all(row["change_type"] and row["source_page"] is None for row in rows if row["source"] == CYTRAIN))

    def test_filters_handle_a_missing_change_type_explicitly(self) -> None:
        not_specified = self.client.get("/analytics/ipc-bns-map", params={"change_type": "not_specified"}).json()
        self.assertEqual((len(not_specified), {row["source"] for row in not_specified}), (68, {NCRB_T1A4}))
        direct = self.client.get("/analytics/ipc-bns-map", params={"change_type": "DIRECT"}).json()
        self.assertTrue(direct and all(row["change_type"] == "DIRECT" for row in direct))
        by_source = self.client.get("/analytics/ipc-bns-map", params={"source": "ncrb_cii_2024_t1a4"}).json()
        self.assertEqual(len(by_source), 68)
        bad = self.client.get("/analytics/ipc-bns-map", params={"change_type": "UNKNOWN"})
        self.assertEqual((bad.status_code, bad.json()["code"]), (400, "INVALID_ANALYTICS_FILTER"))
        self.assertIn("NOT_SPECIFIED", bad.json()["error"])


class MigrationTests(MappingSourceTestCase):
    def tearDown(self) -> None:
        alembic("upgrade", "head")  # leave the test database at head whatever happened

    def test_downgrade_refuses_with_ncrb_rows_then_round_trips(self) -> None:
        load_ipc_bns_mapping(self.db)
        load_ipc_bns_mapping(self.db, source=NCRB_T1A4)
        self.db.close()
        refused = alembic("downgrade", "0010_ncrb_section_labels")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("non-CYTRAIN ipc_bns_mapping row(s) exist", refused.stderr)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM ipc_bns_mapping WHERE source <> 'CYTRAIN'"))
        down = alembic("downgrade", "0010_ncrb_section_labels")
        self.assertEqual(down.returncode, 0, down.stderr)
        with engine.connect() as connection:
            columns = {row[0] for row in connection.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'ipc_bns_mapping'"))}
            self.assertFalse({"source", "source_page"} & columns)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM ipc_bns_mapping")).scalar(), 370)
        up = alembic("upgrade", "head")
        self.assertEqual(up.returncode, 0, up.stderr)
        with engine.connect() as connection:
            self.assertEqual(dict(connection.execute(text("SELECT source, count(*) FROM ipc_bns_mapping GROUP BY source")).all()), {CYTRAIN: 370})
        self.assertIn("No new upgrade operations detected", alembic("check").stdout)


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
