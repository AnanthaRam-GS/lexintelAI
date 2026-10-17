"""Unit and integration tests for LegalAI Task 1.R.3 analytics services."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.core.security import COOKIE_NAME
from backend.app.db.models import Document, DocumentSection, IpcBnsMapping, NcrbStat
from backend.app.db.session import SessionLocal
from backend.app.services.analytics import (
    AnalyticsFilterError,
    get_ipc_bns_mappings,
    get_ncrb_stats,
    get_offence_frequency,
    get_outcome_distribution,
    get_section_cooccurrence,
)
from backend.main import app
from backend.scripts.seed_users import seed_development_users

MARKER = "R3_ANALYTICS_TEST"


class TestAnalyticsServicesAndApi(unittest.TestCase):
    """Tests for analytics query functions, filters, and HTTP endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users()
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.db = SessionLocal()
        self._cleanup()
        self.doc_a = Document(
            doc_type="judgment",
            case_name=f"{MARKER} A",
            court_level="High Court",
            year=2020,
            conviction_status="Convicted",
            appeal_result="Dismissed",
        )
        self.doc_b = Document(
            doc_type="judgment",
            case_name=f"{MARKER} B",
            court_level="Supreme Court",
            year=2020,
            conviction_status="Acquitted",
            appeal_result="Allowed",
        )
        self.doc_c = Document(
            doc_type="judgment",
            case_name=f"{MARKER} C",
            court_level="High Court",
            year=2021,
            conviction_status="Guilty",
            appeal_result="Rejected",
        )
        self.db.add_all([self.doc_a, self.doc_b, self.doc_c])
        self.db.flush()
        self.db.add_all(
            [
                DocumentSection(document_id=self.doc_a.id, statute="IPC", section=f"{MARKER}-302"),
                DocumentSection(document_id=self.doc_a.id, statute="IPC", section=f"{MARKER}-34"),
                DocumentSection(document_id=self.doc_b.id, statute="IPC", section=f"{MARKER}-302"),
                DocumentSection(document_id=self.doc_c.id, statute="IPC", section=f"{MARKER}-376"),
            ]
        )
        self.mapping = IpcBnsMapping(
            ipc_section=f"{MARKER}-302",
            ipc_description="Test murder mapping",
            bns_section="101",
            bns_description="Test BNS murder mapping",
            change_type="DIRECT",
        )
        self.ncrb = NcrbStat(
            year=2024,
            state=f"{MARKER} State",
            offense_category=f"{MARKER} Murder",
            ipc_section="302",
            case_count=12,
            conviction_count=4,
            acquittal_count=2,
        )
        self.db.add_all([self.mapping, self.ncrb])
        self.db.commit()

    def tearDown(self) -> None:
        self._cleanup()
        self.db.close()

    def _cleanup(self) -> None:
        docs = self.db.query(Document).filter(Document.case_name.like(f"{MARKER}%")).all()
        doc_ids = [doc.id for doc in docs]
        if doc_ids:
            self.db.query(DocumentSection).filter(DocumentSection.document_id.in_(doc_ids)).delete(
                synchronize_session=False
            )
            self.db.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
        self.db.query(IpcBnsMapping).filter(IpcBnsMapping.ipc_section.like(f"{MARKER}%")).delete(
            synchronize_session=False
        )
        self.db.query(NcrbStat).filter(NcrbStat.state.like(f"{MARKER}%")).delete(synchronize_session=False)
        self.db.commit()

    def _login(self, email: str = "lawyer@legalai.local", password: str = "LawyerPassword123!") -> TestClient:
        client = TestClient(app)
        response = client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        self.assertIn(COOKIE_NAME, response.cookies)
        return client

    def test_offence_frequency_counts_distinct_documents(self) -> None:
        points = get_offence_frequency(self.db, year=2020, section=f"{MARKER}-302")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].section, f"{MARKER}-302")
        self.assertEqual(points[0].year, 2020)
        self.assertEqual(points[0].count, 2)

    def test_outcome_distribution_normalizes_labels(self) -> None:
        points = {
            (row.section, row.court_level): row
            for row in get_outcome_distribution(self.db, section=f"{MARKER}-302")
        }
        high_court = points[(f"{MARKER}-302", "High Court")]
        supreme_court = points[(f"{MARKER}-302", "Supreme Court")]
        self.assertEqual(high_court.convicted, 1)
        self.assertEqual(high_court.acquitted, 0)
        self.assertEqual(high_court.appeal_dismissed, 1)
        self.assertEqual(high_court.appeal_allowed, 0)
        self.assertEqual(supreme_court.acquitted, 1)
        self.assertEqual(supreme_court.appeal_allowed, 1)

    def test_section_cooccurrence_pairs(self) -> None:
        points = get_section_cooccurrence(self.db, section=f"{MARKER}-302")
        pair = next(
            row
            for row in points
            if {row.section_a, row.section_b} == {f"{MARKER}-34", f"{MARKER}-302"}
        )
        self.assertEqual(pair.count, 1)

    def test_ipc_bns_and_ncrb_filters(self) -> None:
        mappings = get_ipc_bns_mappings(self.db, ipc_section=f"{MARKER}-302", change_type="direct")
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0].bns_section, "101")

        stats = get_ncrb_stats(self.db, state=f"{MARKER} state", year=2024)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].case_count, 12)
        self.assertEqual(stats[0].conviction_count, 4)

    def test_invalid_filters_raise(self) -> None:
        with self.assertRaises(AnalyticsFilterError):
            get_offence_frequency(self.db, year=1800)
        with self.assertRaises(AnalyticsFilterError):
            get_offence_frequency(self.db, section="   ")
        with self.assertRaises(AnalyticsFilterError):
            get_ipc_bns_mappings(self.db, change_type="NOT_A_TYPE")

    def test_analytics_endpoints_require_auth_and_return_rows(self) -> None:
        unauthenticated = TestClient(app)
        response = unauthenticated.get("/analytics/offence-frequency")
        self.assertEqual(response.status_code, 401)

        client = self._login()
        freq = client.get(
            "/analytics/offence-frequency",
            params={"year": 2020, "section": f"{MARKER}-302"},
        )
        self.assertEqual(freq.status_code, 200)
        # Test contract route /analytics/offense-frequency
        freq_contract = client.get(
            "/analytics/offense-frequency",
            params={"year": 2020, "section": f"{MARKER}-302"},
        )
        self.assertEqual(freq_contract.status_code, 200)
        self.assertEqual(freq_contract.json()[0]["count"], 2)

        outcomes = client.get(
            "/analytics/outcome-distribution",
            params={"section": f"{MARKER}-302"},
        )
        self.assertEqual(outcomes.status_code, 200)
        self.assertTrue(any(row["court_level"] == "High Court" for row in outcomes.json()))

        cooccur = client.get(
            "/analytics/section-cooccurrence",
            params={"section": f"{MARKER}-34"},
        )
        self.assertEqual(cooccur.status_code, 200)
        self.assertTrue(any(row["count"] == 1 for row in cooccur.json()))

        # Test both /analytics/ipc-bns and contract route /analytics/ipc-bns-map
        ipc = client.get("/analytics/ipc-bns", params={"ipc_section": f"{MARKER}-302"})
        self.assertEqual(ipc.status_code, 200)
        self.assertEqual(ipc.json()[0]["change_type"], "DIRECT")
        ipc_map = client.get("/analytics/ipc-bns-map", params={"ipc_section": f"{MARKER}-302"})
        self.assertEqual(ipc_map.status_code, 200)
        self.assertEqual(ipc_map.json()[0]["change_type"], "DIRECT")

        # Test both /analytics/ncrb and contract route /analytics/ncrb-stats
        ncrb = client.get("/analytics/ncrb", params={"state": f"{MARKER} State", "ipc_section": "302"})
        self.assertEqual(ncrb.status_code, 200)
        self.assertEqual(ncrb.json()[0]["offense_category"], f"{MARKER} Murder")
        ncrb_stats = client.get("/analytics/ncrb-stats", params={"state": f"{MARKER} State", "ipc_section": "302"})
        self.assertEqual(ncrb_stats.status_code, 200)
        self.assertEqual(ncrb_stats.json()[0]["offense_category"], f"{MARKER} Murder")

        bad = client.get("/analytics/ipc-bns-map", params={"change_type": "UNKNOWN"})
        self.assertEqual(bad.status_code, 400)


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
