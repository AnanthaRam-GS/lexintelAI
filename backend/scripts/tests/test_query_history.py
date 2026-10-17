"""Unit and integration tests for LegalAI Task 1.R.3 query history."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.core.security import COOKIE_NAME, hash_password
from backend.app.db.models import QueryHistory, User
from backend.app.db.session import SessionLocal
from backend.app.services.query_history import list_query_history, save_query_history
from backend.main import app
from backend.scripts.seed_users import seed_development_users

MARKER = "R3_HISTORY_TEST"
SECOND_LAWYER_EMAIL = "lawyer2-r3@legalai.local"


class TestQueryHistoryServiceAndApi(unittest.TestCase):
    """Tests for save_query_history, isolation, and the history endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users()

    def setUp(self) -> None:
        self.db = SessionLocal()
        self._cleanup()
        self.lawyer = self.db.query(User).filter(User.email == "lawyer@legalai.local").one()
        self.admin = self.db.query(User).filter(User.email == "admin@legalai.local").one()
        second = self.db.query(User).filter(User.email == SECOND_LAWYER_EMAIL).first()
        if second is None:
            second = User(
                email=SECOND_LAWYER_EMAIL,
                hashed_password=hash_password("LawyerTwoPassword123!"),
                role="lawyer",
            )
            self.db.add(second)
            self.db.commit()
            self.db.refresh(second)
        self.second_lawyer = second

    def tearDown(self) -> None:
        self._cleanup()
        self.db.close()

    def _cleanup(self) -> None:
        self.db.query(QueryHistory).filter(QueryHistory.query_text.like(f"{MARKER}%")).delete(
            synchronize_session=False
        )
        extra = self.db.query(User).filter(User.email == SECOND_LAWYER_EMAIL).first()
        if extra is not None:
            self.db.query(QueryHistory).filter(QueryHistory.user_id == extra.id).delete(
                synchronize_session=False
            )
            self.db.delete(extra)
        self.db.commit()

    def _login(self, email: str, password: str) -> TestClient:
        client = TestClient(app)
        response = client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        self.assertIn(COOKIE_NAME, response.cookies)
        return client

    def test_save_professional_query_and_list_latest(self) -> None:
        first = save_query_history(
            self.db,
            query_text=f"{MARKER} first",
            mode="professional",
            user_id=self.lawyer.id,
            response_json={"summary": "one"},
            generation_backend="test",
        )
        second = save_query_history(
            self.db,
            query_text=f"{MARKER} second",
            mode="PROFESSIONAL",
            user_id=self.lawyer.id,
            response_json={"summary": "two"},
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

        rows = list_query_history(self.db, user_id=self.lawyer.id, limit=10)
        texts = [row.query_text for row in rows if row.query_text.startswith(MARKER)]
        self.assertEqual(texts[0], f"{MARKER} second")
        self.assertIn(f"{MARKER} first", texts)

    def test_public_and_anonymous_queries_are_not_persisted(self) -> None:
        public_row = save_query_history(
            self.db,
            query_text=f"{MARKER} public",
            mode="public",
            user_id=self.lawyer.id,
            session_id="session-local-1",
        )
        anonymous_row = save_query_history(
            self.db,
            query_text=f"{MARKER} anonymous professional",
            mode="professional",
            user_id=None,
            session_id="session-local-2",
        )
        self.assertIsNone(public_row)
        self.assertIsNone(anonymous_row)
        remaining = (
            self.db.query(QueryHistory)
            .filter(QueryHistory.query_text.in_([f"{MARKER} public", f"{MARKER} anonymous professional"]))
            .count()
        )
        self.assertEqual(remaining, 0)

    def test_user_isolation_on_endpoint(self) -> None:
        save_query_history(
            self.db,
            query_text=f"{MARKER} lawyer one",
            mode="professional",
            user_id=self.lawyer.id,
        )
        save_query_history(
            self.db,
            query_text=f"{MARKER} lawyer two",
            mode="professional",
            user_id=self.second_lawyer.id,
        )

        unauthenticated = TestClient(app)
        self.assertEqual(unauthenticated.get("/query/history").status_code, 401)
        self.assertEqual(unauthenticated.get("/query-history").status_code, 401)

        lawyer_client = self._login("lawyer@legalai.local", "LawyerPassword123!")
        # Test contract route /query/history
        contract_resp = lawyer_client.get("/query/history", params={"limit": 20})
        self.assertEqual(contract_resp.status_code, 200)
        contract_texts = [row["query_text"] for row in contract_resp.json()]
        self.assertIn(f"{MARKER} lawyer one", contract_texts)
        self.assertNotIn(f"{MARKER} lawyer two", contract_texts)

        # Test legacy route /query-history
        lawyer_resp = lawyer_client.get("/query-history", params={"limit": 20})
        self.assertEqual(lawyer_resp.status_code, 200)
        lawyer_texts = [row["query_text"] for row in lawyer_resp.json()]
        self.assertIn(f"{MARKER} lawyer one", lawyer_texts)
        self.assertNotIn(f"{MARKER} lawyer two", lawyer_texts)

        other_client = self._login(SECOND_LAWYER_EMAIL, "LawyerTwoPassword123!")
        other_resp = other_client.get("/query-history")
        self.assertEqual(other_resp.status_code, 200)
        other_texts = [row["query_text"] for row in other_resp.json()]
        self.assertIn(f"{MARKER} lawyer two", other_texts)
        self.assertNotIn(f"{MARKER} lawyer one", other_texts)

    def test_empty_query_text_rejected(self) -> None:
        with self.assertRaises(ValueError):
            save_query_history(
                self.db,
                query_text="   ",
                mode="professional",
                user_id=self.lawyer.id,
            )


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
