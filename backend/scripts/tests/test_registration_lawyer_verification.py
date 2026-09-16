"""Registration and lawyer-verification workflow tests."""

from __future__ import annotations

import secrets
import unittest
from pathlib import Path
import sys

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.db.models import EmailVerificationToken, LawyerVerificationApplication, User
from backend.app.db.session import SessionLocal
from backend.main import app
from backend.scripts.seed_users import seed_development_users


class RegistrationLawyerVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users()

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.marker = secrets.token_hex(6)
        self.email = f"public-{self.marker}@example.test"

    def test_register_creates_public_user_and_ignores_role_injection(self) -> None:
        response = self.client.post(
            "/auth/register",
            json={
                "full_name": "Public User",
                "email": f"  {self.email.upper()}  ",
                "password": "Password123!",
                "role": "lawyer",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["user"]["email"], self.email)
        self.assertEqual(body["user"]["role"], "public")
        self.assertFalse(body["user"]["email_verified"])
        self.assertNotIn("hashed_password", str(body))

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            self.assertEqual(user.role, "public")
            self.assertNotEqual(user.hashed_password, "Password123!")
        finally:
            db.close()

    def test_duplicate_email_and_short_password_are_rejected(self) -> None:
        payload = {"full_name": "Public User", "email": self.email, "password": "Password123!"}
        self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 409)
        weak = dict(payload, email=f"weak-{self.email}", password="short")
        self.assertEqual(self.client.post("/auth/register", json=weak).status_code, 422)

    def test_email_verification_token_is_hashed_single_use(self) -> None:
        self.client.post("/auth/register", json={"full_name": "Verify Me", "email": self.email, "password": "Password123!"})
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            token_row = db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).one()
            self.assertEqual(len(token_row.token_hash), 64)
            self.assertNotIn(self.email, token_row.token_hash)
            token_row.used_at = token_row.expires_at
            user.email_verified = 1
            db.commit()
        finally:
            db.close()

        login = self.client.post("/auth/login", json={"email": self.email, "password": "Password123!"})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["user"]["email_verified"])

    def test_public_and_pending_applicant_are_denied_professional_until_admin_approval(self) -> None:
        public_client = self.register_login_and_verify()
        self.assertEqual(public_client.post("/query/professional", json={"text": "bail research"}).status_code, 403)
        application = public_client.post(
            "/lawyer-applications",
            data={
                "bar_council": "State Bar Council",
                "enrollment_number": f"ENR-{self.marker}",
                "enrollment_year": "2024",
                "jurisdiction": "Kerala",
            },
            files={"proof": ("proof.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        self.assertEqual(application.status_code, 201)
        self.assertEqual(public_client.post("/query/professional", json={"text": "bail research"}).status_code, 403)

        admin = TestClient(app)
        self.assertEqual(admin.post("/auth/login", json={"email": "admin@legalai.local", "password": "AdminPassword123!"}).status_code, 200)
        approved = admin.post(f"/admin/lawyer-applications/{application.json()['id']}/approve")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "VERIFIED")
        self.assertEqual(public_client.get("/auth/me").json()["role"], "lawyer")

    def test_lawyer_application_rejects_anon_unverified_duplicate_and_invalid_proof(self) -> None:
        anon = self.client.post("/lawyer-applications", data={}, files={})
        self.assertEqual(anon.status_code, 401)

        self.client.post("/auth/register", json={"full_name": "Applicant", "email": self.email, "password": "Password123!"})
        self.client.post("/auth/login", json={"email": self.email, "password": "Password123!"})
        unverified = self.client.post(
            "/lawyer-applications",
            data={"bar_council": "X", "enrollment_number": "Y", "enrollment_year": "2024", "jurisdiction": "Z"},
            files={"proof": ("proof.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        self.assertEqual(unverified.status_code, 403)

        self.mark_verified(self.email)
        invalid = self.client.post(
            "/lawyer-applications",
            data={"bar_council": "X", "enrollment_number": "Y", "enrollment_year": "2024", "jurisdiction": "Z"},
            files={"proof": ("proof.txt", b"not proof", "text/plain")},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_reject_keeps_role_public_and_proof_is_not_corpus(self) -> None:
        public_client = self.register_login_and_verify()
        created = public_client.post(
            "/lawyer-applications",
            data={"bar_council": "X", "enrollment_number": f"ISO-{self.marker}", "enrollment_year": "2024", "jurisdiction": "Z"},
            files={"proof": ("proof.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        admin = TestClient(app)
        admin.post("/auth/login", json={"email": "admin@legalai.local", "password": "AdminPassword123!"})
        rejected = admin.post(f"/admin/lawyer-applications/{created.json()['id']}/reject", json={"reason": "Details could not be verified."})
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(public_client.get("/auth/me").json()["role"], "public")

        db = SessionLocal()
        try:
            app_row = db.query(LawyerVerificationApplication).filter(LawyerVerificationApplication.id == created.json()["id"]).one()
            self.assertNotIn("/", app_row.proof_storage_key)
            self.assertEqual(app_row.status, "REJECTED")
        finally:
            db.close()

    def register_login_and_verify(self) -> TestClient:
        client = TestClient(app)
        client.post("/auth/register", json={"full_name": "Applicant", "email": self.email, "password": "Password123!"})
        self.mark_verified(self.email)
        self.assertEqual(client.post("/auth/login", json={"email": self.email, "password": "Password123!"}).status_code, 200)
        return client

    @staticmethod
    def mark_verified(email: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).one()
            user.email_verified = 1
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
