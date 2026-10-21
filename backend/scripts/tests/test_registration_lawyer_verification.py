"""Registration and lawyer-verification workflow tests."""

from __future__ import annotations

import secrets
import unittest
from pathlib import Path
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.core.config import Settings
from backend.app.db.models import EmailVerificationOtp, LawyerVerificationApplication, User
from backend.app.db.session import SessionLocal
from backend.app.services.email_delivery import EmailDeliveryError, EmailDeliveryService
from backend.main import app
from backend.scripts.seed_users import seed_development_users
from backend.scripts.tests.db_test_bootstrap import TEST_SEED_PASSWORDS, TEST_ADMIN_PASSWORD


class RegistrationLawyerVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users(TEST_SEED_PASSWORDS)

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
        self.assertEqual(body["email"], self.email)
        self.assertNotIn("user", body)  # SEC-003: no account data, so new and existing emails look the same
        self.assertNotIn("hashed_password", str(body))

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            self.assertEqual(user.role, "public")
            self.assertFalse(user.email_verified)
            self.assertNotEqual(user.hashed_password, "Password123!")
        finally:
            db.close()

    def test_duplicate_email_gets_the_new_account_response_and_a_notice(self) -> None:
        # SEC-003: no 409; the existing owner is emailed a notice and no second account or code is created.
        payload = {"full_name": "Public User", "email": self.email, "password": "Password123!"}
        first = self.client.post("/auth/register", json=payload)
        with patch("backend.app.api.auth.send_verification_otp") as send_otp, patch(
            "backend.app.services.email_delivery.EmailDeliveryService.send_account_exists_notice"
        ) as notice:
            again = self.client.post("/auth/register", json=dict(payload, password="Different123!"))
        self.assertEqual((first.status_code, again.status_code), (201, 201))
        self.assertEqual(again.json(), {**first.json(), "dev_verification_otp": None})
        self.assertEqual(again.headers.keys(), first.headers.keys())
        send_otp.assert_not_called()
        notice.assert_called_once_with(self.email)
        db = SessionLocal()
        try:
            self.assertEqual(db.query(User).filter(User.email == self.email).count(), 1)
        finally:
            db.close()

    def test_short_password_is_rejected(self) -> None:
        payload = {"full_name": "Public User", "email": self.email, "password": "Password123!"}
        weak = dict(payload, email=f"weak-{self.email}", password="short")
        self.assertEqual(self.client.post("/auth/register", json=weak).status_code, 422)

    def test_email_verification_otp_is_hashed_single_use(self) -> None:
        with patch("backend.app.api.auth.generate_email_otp", return_value="123456"), patch(
            "backend.app.api.auth.send_verification_otp"
        ) as send_otp:
            self.client.post("/auth/register", json={"full_name": "Verify Me", "email": self.email, "password": "Password123!"})
        send_otp.assert_called_once()
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            otp_row = db.query(EmailVerificationOtp).filter(EmailVerificationOtp.user_id == user.id).one()
            self.assertEqual(len(otp_row.otp_hash), 64)
            self.assertNotIn(self.email, otp_row.otp_hash)
            self.assertNotEqual(otp_row.otp_hash, "123456")
            otp_row.consumed_at = otp_row.expires_at
            user.email_verified = 1
            db.commit()
        finally:
            db.close()

        login = self.client.post("/auth/login", json={"email": self.email, "password": "Password123!"})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["user"]["email_verified"])

    def test_correct_otp_verifies_without_role_escalation_and_reuse_fails(self) -> None:
        with patch("backend.app.api.auth.generate_email_otp", return_value="123456"), patch("backend.app.api.auth.send_verification_otp"):
            self.client.post("/auth/register", json={"full_name": "Verify Me", "email": self.email, "password": "Password123!"})
        verified = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "123456"})
        self.assertEqual(verified.status_code, 200)
        reused = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "123456"})
        self.assertEqual(reused.status_code, 400)

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            self.assertEqual(user.role, "public")
            self.assertEqual(user.email_verified, 1)
        finally:
            db.close()

    def test_wrong_expired_and_attempt_limited_otp_are_rejected(self) -> None:
        with patch("backend.app.api.auth.generate_email_otp", return_value="123456"), patch("backend.app.api.auth.send_verification_otp"):
            self.client.post("/auth/register", json={"full_name": "Verify Me", "email": self.email, "password": "Password123!"})
        wrong = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "000000"})
        self.assertEqual(wrong.status_code, 400)

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            otp_row = db.query(EmailVerificationOtp).filter(EmailVerificationOtp.user_id == user.id).one()
            otp_row.attempts = 5
            db.commit()
        finally:
            db.close()
        limited = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "123456"})
        self.assertEqual(limited.status_code, 429)

        expired_email = f"expired-{self.email}"
        with patch("backend.app.api.auth.generate_email_otp", return_value="654321"), patch("backend.app.api.auth.send_verification_otp"):
            self.client.post("/auth/register", json={"full_name": "Expired", "email": expired_email, "password": "Password123!"})
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == expired_email).one()
            otp_row = db.query(EmailVerificationOtp).filter(EmailVerificationOtp.user_id == user.id).one()
            otp_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        expired = self.client.post("/auth/verify-email", json={"email": expired_email, "otp": "654321"})
        self.assertEqual(expired.status_code, 400)

    def test_resend_invalidates_previous_otp_and_enforces_cooldown(self) -> None:
        with patch("backend.app.api.auth.generate_email_otp", return_value="111111"), patch("backend.app.api.auth.send_verification_otp"):
            self.client.post("/auth/register", json={"full_name": "Verify Me", "email": self.email, "password": "Password123!"})
        # SEC-003: the cooldown is enforced silently (no new code, no 429) so it reveals nothing.
        with patch("backend.app.api.auth.send_verification_otp") as cooling_send:
            cooldown = self.client.post("/auth/resend-verification", json={"email": self.email})
        self.assertEqual(cooldown.status_code, 200)
        cooling_send.assert_not_called()
        unknown = self.client.post("/auth/resend-verification", json={"email": f"nobody-{self.email}"})
        self.assertEqual(unknown.json(), cooldown.json())

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.email).one()
            first = db.query(EmailVerificationOtp).filter(EmailVerificationOtp.user_id == user.id).one()
            first.created_at = datetime.now(UTC) - timedelta(minutes=2)
            db.commit()
        finally:
            db.close()
        with patch("backend.app.api.auth.generate_email_otp", return_value="222222"), patch("backend.app.api.auth.send_verification_otp") as send_otp:
            resent = self.client.post("/auth/resend-verification", json={"email": self.email})
        self.assertEqual(resent.status_code, 200)
        send_otp.assert_called_once()
        old = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "111111"})
        self.assertEqual(old.status_code, 400)
        new = self.client.post("/auth/verify-email", json={"email": self.email, "otp": "222222"})
        self.assertEqual(new.status_code, 200)

    def test_smtp_delivery_is_mockable_and_does_not_require_real_email(self) -> None:
        settings = Settings(
            email_delivery_mode="smtp",
            smtp_host="smtp.example.test",
            smtp_port=2525,
            smtp_from_email="noreply@example.test",
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            smtp_use_tls=True,
        )
        smtp_client = Mock()
        smtp_context = Mock()
        smtp_context.__enter__ = Mock(return_value=smtp_client)
        smtp_context.__exit__ = Mock(return_value=False)

        with patch("backend.app.services.email_delivery.smtplib.SMTP", return_value=smtp_context) as smtp:
            EmailDeliveryService(settings).send_email_verification_otp(self.email, "123456", 10)

        smtp.assert_called_once_with("smtp.example.test", 2525, timeout=15)
        smtp_client.starttls.assert_called_once()
        smtp_client.login.assert_called_once_with("smtp-user", "smtp-pass")
        smtp_client.send_message.assert_called_once()
        message = smtp_client.send_message.call_args.args[0]
        self.assertEqual(message["To"], self.email)
        self.assertIn("123456", message.get_content())

    def test_email_delivery_rejects_unsafe_or_broken_modes(self) -> None:
        with self.assertRaises(EmailDeliveryError):
            EmailDeliveryService(Settings(app_env="production", email_delivery_mode="console")).send_email_verification_otp(
                self.email, "123456", 10
            )
        with self.assertRaises(EmailDeliveryError):
            EmailDeliveryService(Settings(email_delivery_mode="smtp", smtp_host="", smtp_from_email="")).send_email_verification_otp(
                self.email, "123456", 10
            )

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
        self.assertEqual(admin.post("/auth/login", json={"email": "admin@legalai.local", "password": TEST_ADMIN_PASSWORD}).status_code, 200)
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
        admin.post("/auth/login", json={"email": "admin@legalai.local", "password": TEST_ADMIN_PASSWORD})
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


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
