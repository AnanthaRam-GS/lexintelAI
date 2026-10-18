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
from backend.app.db.models import Chunk, Document, DocumentSection, IpcBnsMapping, NcrbStat
from backend.app.services.judgment_sections import EXTRACTION_METHOD as SECTION_METHOD
from backend.scripts import verify_analytics
from backend.scripts.produce_analytics_data import produce
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
        # Labels are statute-qualified ("IPC 302"), the frontend contract.
        self.assertEqual(points[0].section, f"IPC {MARKER}-302")
        self.assertEqual(points[0].year, 2020)
        self.assertEqual(points[0].count, 2)
        # The full label filters the same rows as the bare section number.
        self.assertEqual(get_offence_frequency(self.db, year=2020, section=f"IPC {MARKER}-302"), points)

    def test_outcome_distribution_normalizes_labels(self) -> None:
        points = {
            (row.section, row.court_level): row
            for row in get_outcome_distribution(self.db, section=f"{MARKER}-302")
        }
        high_court = points[(f"IPC {MARKER}-302", "High Court")]
        supreme_court = points[(f"IPC {MARKER}-302", "Supreme Court")]
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
            if {row.section_a, row.section_b} == {f"IPC {MARKER}-34", f"IPC {MARKER}-302"}
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


ANALYTICS_ENDPOINTS = (
    "/analytics/offense-frequency",
    "/analytics/outcome-distribution",
    "/analytics/section-cooccurrence",
    "/analytics/ipc-bns-map",
    "/analytics/ncrb-stats",
)


class TestAnalyticsProducerAndReconciliation(unittest.TestCase):
    """Producer (sections, outcomes, court level) and endpoint reconciliation with SQL."""

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users()

    def setUp(self) -> None:
        self.db = SessionLocal()
        self.client = TestClient(app)
        login = self.client.post("/auth/login", json={"email": "lawyer@legalai.local", "password": "LawyerPassword123!"})
        self.assertEqual(login.status_code, 200)

    def tearDown(self) -> None:
        self.db.close()

    def add_document(self, key: str, chunks: list[str], **fields) -> Document:
        document = Document(doc_type="judgment", case_name=f"{MARKER} {key}", source_document_key=key, checksum=key, **fields)
        document.chunks = [
            Chunk(chunk_index=index, text=text, chroma_id=f"{key}:chunk:{index:04d}") for index, text in enumerate(chunks)
        ]
        self.db.add(document)
        self.db.commit()
        return document

    def seed_corpus(self) -> dict[str, Document]:
        docs = {
            "dismissed": self.add_document(
                "test:dismissed",
                [
                    "The accused was charged under Sections 302/34 IPC and Section 201 IPC.",
                    "His statement under Section 313 Cr.P.C. was recorded.",
                    "In the result, the appeal is dismissed. The conviction of the appellant is upheld.",
                ],
                court_name="Delhi High Court",
                year=2023,
            ),
            "acquitted": self.add_document(
                "test:acquitted",
                [
                    "Offences under Section 302 IPC and Section 103 BNS were alleged.",
                    "The appeal is allowed and the appellants are acquitted of all charges.",
                ],
                court_name="Supreme Court of India",
                court_level="supreme_court",
                year=2024,
            ),
            "ambiguous": self.add_document(
                "test:ambiguous",
                [
                    "Charged under Section 307 IPC; the trial court record was perused.",
                    "Accused No. 1 is acquitted. The conviction of Accused No. 2 under Section 307 IPC is upheld.",
                ],
                court_name="Patna High Court",
                year=2022,
            ),
            "manual": self.add_document(
                "test:manual",
                ["Section 420 IPC was invoked.", "The appellants are acquitted."],
                court_name="Bombay High Court",
                year=2021,
                conviction_status="convicted",  # pre-existing value from another source
            ),
        }
        return docs

    def test_endpoints_return_empty_arrays_for_an_empty_dataset(self) -> None:
        for path in ANALYTICS_ENDPOINTS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

    def test_producer_writes_sections_and_outcomes_with_provenance_idempotently(self) -> None:
        docs = self.seed_corpus()
        first = produce(self.db, dry_run=False)
        self.db.expire_all()

        sections = {
            (row.statute, row.section): row
            for row in self.db.query(DocumentSection).filter_by(document_id=docs["dismissed"].id)
        }
        self.assertEqual(set(sections), {("IPC", "302"), ("IPC", "34"), ("IPC", "201"), ("CrPC", "313")})
        for row in self.db.query(DocumentSection).all():
            self.assertIsNotNone(row.evidence_chunk_id)
            self.assertGreaterEqual(row.mention_count, 1)
            self.assertGreaterEqual(row.chunk_count, 1)
            self.assertEqual(row.extraction_method, SECTION_METHOD)
        self.assertEqual(sections[("IPC", "302")].evidence_chunk_id, "test:dismissed:chunk:0000")

        dismissed = self.db.get(Document, docs["dismissed"].id)
        self.assertEqual(
            (dismissed.appeal_result, dismissed.conviction_status, dismissed.case_disposition),
            ("dismissed", "convicted", "appeal dismissed"),
        )
        self.assertEqual(dismissed.court_level, "high_court")  # derived from the court name
        self.assertEqual(set(dismissed.outcome_evidence), {"appeal_result", "conviction_status", "case_disposition"})
        self.assertEqual(dismissed.outcome_evidence["conviction_status"], {"rule": "conviction_upheld", "chunk_id": "test:dismissed:chunk:0002"})

        acquitted = self.db.get(Document, docs["acquitted"].id)
        self.assertEqual((acquitted.conviction_status, acquitted.appeal_result), ("acquitted", "allowed"))
        self.assertIn(("BNS", "103"), {(r.statute, r.section) for r in acquitted.document_sections})

        ambiguous = self.db.get(Document, docs["ambiguous"].id)
        self.assertIsNone(ambiguous.conviction_status)  # co-accused differ: never guessed
        self.assertNotIn("conviction_status", ambiguous.outcome_evidence or {})

        manual = self.db.get(Document, docs["manual"].id)
        self.assertEqual(manual.conviction_status, "convicted")  # value from another source kept
        self.assertEqual(first["outcomes_kept_other_method"]["conviction_status"], 1)

        # Every non-null outcome value has evidence.
        for document in self.db.query(Document).all():
            for field in ("conviction_status", "appeal_result", "case_disposition"):
                if getattr(document, field) is not None and document.id != manual.id:
                    self.assertIn(field, document.outcome_evidence)

        second = produce(self.db, dry_run=False)
        self.assertEqual(second["sections"]["inserted"] + second["sections"]["updated"] + second["sections"]["deleted"], 0)
        self.assertEqual(sum(second["outcomes_changed"].values()), 0)
        self.assertEqual(second["court_level"]["filled"], 0)

    def test_dry_run_writes_nothing(self) -> None:
        self.seed_corpus()
        stats = produce(self.db, dry_run=True)
        self.assertGreater(stats["sections"]["inserted"], 0)
        self.db.expire_all()
        self.assertEqual(self.db.query(DocumentSection).count(), 0)
        self.assertTrue(all(d.outcome_method is None for d in self.db.query(Document).all()))

    def test_endpoints_reconcile_with_direct_sql(self) -> None:
        self.seed_corpus()
        produce(self.db, dry_run=False)
        self.db.add(IpcBnsMapping(ipc_section="302", ipc_description="Murder", bns_section="103", bns_description="Murder", change_type="DIRECT"))
        self.db.add(NcrbStat(year=2024, state=f"{MARKER} State", offense_category="Murder", ipc_section="302", case_count=None, conviction_count=None, acquittal_count=None))
        self.db.commit()

        for path in ANALYTICS_ENDPOINTS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json())
        self.assertIsNone(self.client.get("/analytics/ncrb-stats").json()[0]["case_count"])  # NULL, not 0
        self.assertEqual(verify_analytics.main(["--database-url-env", "TEST_DATABASE_URL", "--require-non-empty"]), 0)

        frequency = {(row["section"], row["year"]): row["count"] for row in self.client.get("/analytics/offense-frequency").json()}
        self.assertEqual(frequency[("IPC 302", 2023)], 1)
        self.assertEqual(frequency[("BNS 103", 2024)], 1)


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
