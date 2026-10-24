"""Security hardening (step 13): SEC-001 to SEC-009 and negative authorization, against the isolated test DB.

No network, no LLM calls: provider adapters and slow generation are mocked.
"""

from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
import hashlib
import io
import os
import secrets
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from fastapi.testclient import TestClient

from backend.app.api import ingest as ingest_api
from backend.app.api import query as query_api
from backend.app.core import rate_limit, startup_checks
from backend.app.core.config import Settings
from backend.app.core.known_credentials import historical_seed_passwords
from backend.app.core.rate_limit import client_ip, reset_limits
from backend.app.core.request_guards import BodySizeLimitMiddleware
from backend.app.core.security import COOKIE_NAME, create_access_token, get_cookie_options, hash_password
from backend.app.db.models import LawyerVerificationApplication, QueryHistory, User
from backend.app.db.session import SessionLocal
from backend.app.services.legal_answer_generation import AnswerMode, LegalAnswerModelResponse, ModelGenerationMetadata
from backend.main import app
import backend.main as main_module
from backend.scripts import seed_users
from backend.scripts.tests.test_legal_answer_foundation import retrieval

ALLOWED_ORIGIN = "http://localhost:3000"


def make_user(*, role: str = "public", active: bool = True, password: str | None = None) -> tuple[User, str]:
    password = password or secrets.token_urlsafe(16)
    db = SessionLocal()
    try:
        user = User(
            email=f"{role}-{secrets.token_hex(6)}@example.test",
            full_name=f"Test {role}",
            hashed_password=hash_password(password),
            role=role,
            email_verified=1,
            is_active=1 if active else 0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user, password
    finally:
        db.close()


def set_active(user_id: int, active: bool) -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).update({"is_active": 1 if active else 0})
        db.commit()
    finally:
        db.close()


def reset_password(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).update({"hashed_password": hash_password(secrets.token_urlsafe(16))})
        db.commit()
    finally:
        db.close()


def client_for(user: User, *, role_claim: str | None = None, expires: timedelta | None = None) -> TestClient:
    client = TestClient(app)
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": role_claim or user.role}, expires_delta=expires)
    client.cookies.set(COOKIE_NAME, token)
    return client


class SecurityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_limits()
        self.addCleanup(reset_limits)
        self.addCleanup(app.dependency_overrides.clear)


class SeedCredentialTests(SecurityTestCase):
    """SEC-002."""

    def test_seed_script_refuses_without_env_vars_and_in_production(self) -> None:
        with self.assertRaisesRegex(seed_users.SeedRefused, "SEED_LAWYER_PASSWORD is not set.*SEED_ADMIN_PASSWORD is not set"):
            seed_users.seed_passwords({}, app_env="development")
        good = {"SEED_LAWYER_PASSWORD": secrets.token_urlsafe(16), "SEED_ADMIN_PASSWORD": secrets.token_urlsafe(16)}
        with self.assertRaisesRegex(seed_users.SeedRefused, "APP_ENV=production"):
            seed_users.seed_passwords(good, app_env="production")
        self.assertEqual(sorted(seed_users.seed_passwords(good, app_env="development")), ["admin@legalai.local", "lawyer@legalai.local"])

    def test_seed_script_refuses_short_and_historical_passwords_without_printing_them(self) -> None:
        historical = historical_seed_passwords()[0]
        env = {"SEED_LAWYER_PASSWORD": historical, "SEED_ADMIN_PASSWORD": "short"}
        with self.assertRaises(seed_users.SeedRefused) as raised:
            seed_users.seed_passwords(env, app_env="development")
        self.assertIn("known historical seed password", str(raised.exception))
        self.assertIn("shorter than 12", str(raised.exception))
        self.assertNotIn(historical, str(raised.exception))

        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"SEED_LAWYER_PASSWORD": "", "SEED_ADMIN_PASSWORD": historical}), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(seed_users.main(), 1)
        self.assertNotIn(historical, out.getvalue() + err.getvalue())

    def test_startup_refuses_production_when_a_user_has_a_seed_password(self) -> None:
        user, _ = make_user(role="admin", password=historical_seed_passwords()[1])
        self.addCleanup(reset_password, user.id)
        production = Settings(app_env="production", jwt_secret_key=secrets.token_urlsafe(48))
        with self.assertRaises(startup_checks.InsecureConfigurationError) as raised:
            startup_checks.validate_no_seed_passwords(production, SessionLocal)
        self.assertIn(str(user.id), str(raised.exception))
        self.assertNotIn(historical_seed_passwords()[1], str(raised.exception))
        self.assertNotIn(user.email, str(raised.exception))
        # Development and test are exempt; production passes once the password is changed.
        startup_checks.validate_no_seed_passwords(Settings(app_env="development"), SessionLocal)
        reset_password(user.id)
        startup_checks.validate_no_seed_passwords(production, SessionLocal)

    def test_app_startup_runs_the_checks(self) -> None:
        user, _ = make_user(role="lawyer", password=historical_seed_passwords()[0])
        self.addCleanup(reset_password, user.id)
        with patch.object(main_module.settings, "app_env", "production"), patch.object(
            main_module.settings, "jwt_secret_key", secrets.token_urlsafe(48)
        ), patch.object(main_module.settings, "legalai_model_warmup", False):
            with self.assertRaises(startup_checks.InsecureConfigurationError):
                with TestClient(app):
                    pass
        reset_password(user.id)
        with patch.object(main_module.settings, "app_env", "production"), patch.object(
            main_module.settings, "jwt_secret_key", secrets.token_urlsafe(48)
        ), patch.object(main_module.settings, "legalai_model_warmup", False), patch.object(main_module, "reap_stale_jobs", return_value=[]):
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)


class JwtSecretTests(SecurityTestCase):
    """SEC-005."""

    def test_missing_default_or_short_secret_refuses_outside_test(self) -> None:
        default_value = "x" * 40
        with patch.object(startup_checks, "PUBLIC_JWT_SECRET_SHA256", hashlib.sha256(default_value.encode()).hexdigest()):
            for env in ("development", "production", "staging"):
                for secret, reason in (("", "not set"), (default_value, "old public default"), ("too-short-secret", "shorter than 32")):
                    with self.subTest(env=env, reason=reason):
                        with self.assertRaises(startup_checks.InsecureConfigurationError) as raised:
                            startup_checks.validate_jwt_secret(Settings(app_env=env, jwt_secret_key=secret))
                        self.assertIn(reason, str(raised.exception))
                        if secret:
                            self.assertNotIn(secret, str(raised.exception))
            startup_checks.validate_jwt_secret(Settings(app_env="test", jwt_secret_key=""))
            startup_checks.validate_jwt_secret(Settings(app_env="production", jwt_secret_key=secrets.token_urlsafe(48)))

    def test_the_public_default_is_no_longer_in_the_code(self) -> None:
        security_source = (REPO_ROOT / "backend/app/core/security.py").read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_DEV_SECRET", security_source)
        self.assertNotIn("must-be-at-least-32-bytes", security_source)


class CookieTests(SecurityTestCase):
    """SEC-006 cookie flags."""

    def test_cookie_flags(self) -> None:
        dev = get_cookie_options(Settings(app_env="development"))
        prod = get_cookie_options(Settings(app_env="production", jwt_secret_key=secrets.token_urlsafe(48)))
        self.assertEqual((dev["httponly"], dev["secure"], dev["samesite"]), (True, False, "lax"))
        self.assertEqual((prod["httponly"], prod["secure"], prod["samesite"]), (True, True, "lax"))
        self.assertTrue(get_cookie_options(Settings(app_env="development", auth_cookie_samesite="none"))["secure"])
        self.assertEqual(get_cookie_options(Settings(app_env="development", auth_cookie_samesite="bogus"))["samesite"], "lax")

    def test_login_sets_an_httponly_samesite_cookie(self) -> None:
        user, password = make_user(role="lawyer")
        response = TestClient(app).post("/auth/login", json={"email": user.email, "password": password})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)


class InactiveUserTests(SecurityTestCase):
    """SEC-004."""

    def test_inactive_user_cannot_log_in_and_gets_the_generic_failure(self) -> None:
        user, password = make_user(role="lawyer", active=False)
        client = TestClient(app)
        inactive = client.post("/auth/login", json={"email": user.email, "password": password})
        wrong = client.post("/auth/login", json={"email": user.email, "password": "not-the-password"})
        self.assertEqual(inactive.status_code, 401)
        self.assertEqual(inactive.json(), wrong.json())
        self.assertNotIn(COOKIE_NAME, inactive.cookies)

    def test_deactivated_user_token_is_rejected_on_every_authenticated_route(self) -> None:
        user, _ = make_user(role="admin")
        client = client_for(user)
        self.assertEqual(client.get("/auth/me").status_code, 200)
        set_active(user.id, False)
        for method, path in (
            ("get", "/auth/me"),
            ("get", "/query/history"),
            ("get", "/analytics/ncrb"),
            ("get", "/admin/lawyer-applications"),
            ("get", "/ingest/corpus/stats"),
            ("get", "/lawyer-applications/me"),
            ("post", "/query/professional"),
        ):
            with self.subTest(path=path):
                response = getattr(client, method)(path, **({"json": {"text": "bail"}} if method == "post" else {}))
                self.assertEqual(response.status_code, 401)
                # SEC-004: the same body as a bad or expired-subject token.
                self.assertEqual(response.json(), {"error": "Your session is not valid. Please sign in again.", "code": "INVALID_SESSION", "detail": None})


class LoginThrottleTests(SecurityTestCase):
    """SEC-003 login throttling and enumeration."""

    def test_existing_and_unknown_emails_get_identical_failures_and_throttling(self) -> None:
        user, _ = make_user(role="public")
        unknown = f"nobody-{secrets.token_hex(4)}@example.test"
        with patch.dict(os.environ, {"LOGIN_MAX_FAILURES_PER_ACCOUNT": "3", "LOGIN_LOCKOUT_SECONDS": "600"}):
            results = {}
            for email in (user.email, unknown):
                client = TestClient(app)
                responses = [client.post("/auth/login", json={"email": email, "password": "wrong-password"}) for _ in range(4)]
                results[email] = [(r.status_code, r.json(), "retry-after" in r.headers) for r in responses]
            self.assertEqual(results[user.email], results[unknown])
            statuses = [status for status, _body, _retry in results[user.email]]
            self.assertEqual(statuses, [401, 401, 401, 429])
            last = TestClient(app).post("/auth/login", json={"email": user.email, "password": "wrong-password"})
            self.assertEqual(last.json()["code"], "LOGIN_THROTTLED")
            self.assertLessEqual(int(last.headers["retry-after"]), 600)
            self.assertGreater(int(last.headers["retry-after"]), 590)

    def test_correct_password_is_refused_while_locked_and_success_resets_the_count(self) -> None:
        user, password = make_user(role="lawyer")
        client = TestClient(app)
        with patch.dict(os.environ, {"LOGIN_MAX_FAILURES_PER_ACCOUNT": "2"}):
            client.post("/auth/login", json={"email": user.email, "password": "wrong"})
            self.assertEqual(client.post("/auth/login", json={"email": user.email, "password": password}).status_code, 200)
            client.post("/auth/login", json={"email": user.email, "password": "wrong"})
            self.assertEqual(client.post("/auth/login", json={"email": user.email, "password": password}).status_code, 200)
            for _ in range(2):
                client.post("/auth/login", json={"email": user.email, "password": "wrong"})
            locked = client.post("/auth/login", json={"email": user.email, "password": password})
        self.assertEqual(locked.status_code, 429)
        self.assertNotIn(COOKIE_NAME, locked.cookies)

    def test_per_ip_throttling_across_many_emails(self) -> None:
        with patch.dict(os.environ, {"LOGIN_MAX_FAILURES_PER_IP": "3"}):
            client = TestClient(app)
            statuses = [
                client.post("/auth/login", json={"email": f"spray-{index}@example.test", "password": "x"}).status_code for index in range(4)
            ]
        self.assertEqual(statuses, [401, 401, 401, 429])

    def test_client_ip_trusts_forwarded_for_only_from_configured_proxies(self) -> None:
        def request(peer: str, forwarded: str | None = None) -> SimpleNamespace:
            headers = {"x-forwarded-for": forwarded} if forwarded else {}
            return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)

        untrusted = Settings(trusted_proxies="")
        trusted = Settings(trusted_proxies="10.0.0.0/8, 192.168.1.5")
        self.assertEqual(client_ip(request("203.0.113.9", "1.2.3.4"), untrusted), "203.0.113.9")
        self.assertEqual(client_ip(request("10.0.0.2", "1.2.3.4"), untrusted), "10.0.0.2")
        self.assertEqual(client_ip(request("10.0.0.2", "1.2.3.4"), trusted), "1.2.3.4")
        # A spoofed left-most entry is ignored: the right-most untrusted hop is the client.
        self.assertEqual(client_ip(request("10.0.0.2", "6.6.6.6, 1.2.3.4, 192.168.1.5"), trusted), "1.2.3.4")
        self.assertEqual(client_ip(request("203.0.113.9", "1.2.3.4"), trusted), "203.0.113.9")


class RegistrationEnumerationTests(SecurityTestCase):
    """SEC-003 registration, resend and verify responses do not reveal accounts."""

    def test_register_resend_and_verify_are_identical_for_existing_and_new_emails(self) -> None:
        existing, _ = make_user(role="public")
        new_email = f"new-{secrets.token_hex(4)}@example.test"
        client = TestClient(app)
        with patch("backend.app.services.email_delivery.EmailDeliveryService.send_account_exists_notice") as notice:
            old = client.post("/auth/register", json={"full_name": "A", "email": existing.email, "password": "Password123!"})
        new = client.post("/auth/register", json={"full_name": "B", "email": new_email, "password": "Password123!"})
        notice.assert_called_once_with(existing.email)
        self.assertEqual((old.status_code, new.status_code), (201, 201))
        self.assertEqual({**old.json(), "email": None}, {**new.json(), "email": None})

        verified_resend = client.post("/auth/resend-verification", json={"email": existing.email})
        unknown_resend = client.post("/auth/resend-verification", json={"email": f"ghost-{new_email}"})
        self.assertEqual((verified_resend.status_code, verified_resend.json()), (unknown_resend.status_code, unknown_resend.json()))

        no_code = client.post("/auth/verify-email", json={"email": existing.email, "otp": "123456"})
        unknown = client.post("/auth/verify-email", json={"email": f"ghost-{new_email}", "otp": "123456"})
        self.assertEqual((no_code.status_code, no_code.json()), (unknown.status_code, unknown.json()))


def stub_public_answer(delay: float = 0.0):
    class SlowAdapter:
        calls = 0
        active = 0
        peak = 0
        lock = threading.Lock()

        def generate_structured_answer(self, prompt, *, schema, mode):
            with SlowAdapter.lock:
                SlowAdapter.calls += 1
                SlowAdapter.active += 1
                SlowAdapter.peak = max(SlowAdapter.peak, SlowAdapter.active)
            time.sleep(delay)
            with SlowAdapter.lock:
                SlowAdapter.active -= 1
            return LegalAnswerModelResponse(
                raw_response="{}",
                parsed_response={
                    "answer": {"summary": "ok", "what_this_may_mean": [], "possible_legal_provisions": [], "possible_next_steps": [],
                               "important_cautions": [], "citations": []},
                    "summary": "ok",
                    "claims": [{"claim_id": "c1", "text": "The retrieved authority discusses the question.", "claim_type": "LEGAL_RULE",
                                "citations": [{"evidence_id": "E1", "claim_id": "c1", "supported_text": "fixture", "source_metadata": {}}]}],
                },
                model_metadata=ModelGenerationMetadata(provider="fixture", configured_model_id="fixture-model", response_mode=mode),
            )

    return SlowAdapter


class QueryRateLimitTests(SecurityTestCase):
    """SEC-001."""

    def setUp(self) -> None:
        super().setUp()
        self.adapter_class = stub_public_answer()
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: object()
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: self.adapter_class()
        patcher = patch.object(query_api, "retrieve_legal_evidence", return_value=retrieval())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_public_query_is_limited_per_ip_with_retry_after(self) -> None:
        client = TestClient(app)
        with patch.dict(os.environ, {"PUBLIC_QUERY_LIMIT_PER_MINUTE": "2", "PUBLIC_QUERY_LIMIT_PER_DAY": "100"}):
            statuses = [client.post("/query/public", json={"text": "What is bail?"}).status_code for _ in range(3)]
            limited = client.post("/query/public", json={"text": "What is bail?"})
        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(limited.json()["code"], "RATE_LIMITED")
        self.assertIn("Please wait", limited.json()["error"])
        self.assertTrue(1 <= int(limited.headers["retry-after"]) <= 60)
        self.assertEqual(self.adapter_class.calls, 2)  # the limited requests never reached the provider

    def test_public_daily_limit_and_pdf_route_share_the_ip_budget(self) -> None:
        client = TestClient(app)
        with patch.dict(os.environ, {"PUBLIC_QUERY_LIMIT_PER_MINUTE": "100", "PUBLIC_QUERY_LIMIT_PER_DAY": "1"}):
            self.assertEqual(client.post("/query/public", json={"text": "What is bail?"}).status_code, 200)
            pdf = client.post("/query/public/pdf", data={"query": "q"}, files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(pdf.status_code, 429)
        self.assertGreater(int(pdf.headers["retry-after"]), 3600)

    def test_professional_query_is_limited_per_user(self) -> None:
        lawyer_a, _ = make_user(role="lawyer")
        lawyer_b, _ = make_user(role="lawyer")
        with patch.dict(os.environ, {"PROFESSIONAL_QUERY_LIMIT_PER_MINUTE": "1"}), patch.object(query_api, "save_query_history"):
            first = client_for(lawyer_a).post("/query/professional", json={"text": "bail under section 437"})
            second = client_for(lawyer_a).post("/query/professional", json={"text": "bail under section 437"})
            other = client_for(lawyer_b).post("/query/professional", json={"text": "bail under section 437"})
        self.assertNotEqual(first.status_code, 429)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")
        self.assertIn("retry-after", second.headers)
        self.assertNotEqual(other.status_code, 429)

    def test_anonymous_professional_request_is_401_not_counted(self) -> None:
        with patch.dict(os.environ, {"PROFESSIONAL_QUERY_LIMIT_PER_MINUTE": "0"}):
            self.assertEqual(TestClient(app).post("/query/professional", json={"text": "bail"}).status_code, 401)

    def test_concurrent_generations_are_capped_and_excess_requests_get_503(self) -> None:
        self.adapter_class = stub_public_answer(delay=0.8)
        env = {"LLM_MAX_CONCURRENT_GENERATIONS": "2", "LLM_GENERATION_WAIT_SECONDS": "0.2", "PUBLIC_QUERY_LIMIT_PER_MINUTE": "100"}
        results: list[tuple[int, dict, str | None]] = []
        lock = threading.Lock()

        def ask() -> None:
            response = TestClient(app).post("/query/public", json={"text": "What is bail?"})
            with lock:
                results.append((response.status_code, response.json(), response.headers.get("retry-after")))

        with patch.dict(os.environ, env):
            threads = [threading.Thread(target=ask) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        statuses = sorted(status for status, _body, _retry in results)
        self.assertEqual(statuses, [200, 200, 503, 503])
        busy = [body for status, body, _retry in results if status == 503]
        self.assertTrue(all(body["code"] == "MODEL_BUSY" for body in busy))
        self.assertTrue(all(retry == str(query_api.MODEL_BUSY_RETRY_AFTER_SECONDS) for status, _b, retry in results if status == 503))
        self.assertEqual(self.adapter_class.peak, 2)
        self.assertEqual(self.adapter_class.calls, 2)


class CsrfOriginTests(SecurityTestCase):
    """SEC-006 Origin/Referer validation."""

    def test_cross_origin_cookie_writes_are_rejected_and_same_origin_works(self) -> None:
        user, _ = make_user(role="lawyer")
        evil = client_for(user).post("/auth/logout", headers={"Origin": "https://evil.example"})
        self.assertEqual(evil.status_code, 403)
        self.assertEqual(evil.json()["code"], "CSRF_ORIGIN_REJECTED")
        referer = client_for(user).post("/auth/logout", headers={"Referer": "https://evil.example/page"})
        self.assertEqual(referer.status_code, 403)
        null_origin = client_for(user).post("/auth/logout", headers={"Origin": "null"})
        self.assertEqual(null_origin.status_code, 403)
        same = client_for(user).post("/auth/logout", headers={"Origin": ALLOWED_ORIGIN})
        self.assertEqual(same.status_code, 200)
        same_referer = client_for(user).post("/auth/logout", headers={"Referer": f"{ALLOWED_ORIGIN}/professional"})
        self.assertEqual(same_referer.status_code, 200)

    def test_reads_and_cookieless_requests_are_not_blocked(self) -> None:
        user, password = make_user(role="lawyer")
        self.assertEqual(client_for(user).get("/auth/me", headers={"Origin": "https://evil.example"}).status_code, 200)
        login = TestClient(app).post("/auth/login", json={"email": user.email, "password": password}, headers={"Origin": "https://evil.example"})
        self.assertEqual(login.status_code, 200)  # no auth cookie yet, so nothing to forge


class UploadSizeTests(SecurityTestCase):
    """SEC-008."""

    def test_oversize_content_length_is_rejected_before_the_body_is_read(self) -> None:
        received = {"bytes": 0, "calls": 0}

        async def downstream(scope, receive, send):  # pragma: no cover - must not be reached
            raise AssertionError("route reached")

        async def receive():
            received["calls"] += 1
            body = b"x" * (1024 * 1024)
            received["bytes"] += len(body)
            return {"type": "http.request", "body": body, "more_body": True}

        sent = []

        async def send(message):
            sent.append(message)

        middleware = BodySizeLimitMiddleware(downstream, max_body_bytes=10 * 1024 * 1024)
        scope = {"type": "http", "method": "POST", "path": "/ingest/upload", "headers": [(b"content-length", str(200 * 1024 * 1024).encode())]}
        asyncio.run(middleware(scope, receive, send))
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(received, {"bytes": 0, "calls": 0})

    def test_streamed_admin_upload_stops_reading_just_past_the_limit(self) -> None:
        class CountingUpload:
            def __init__(self, size: int) -> None:
                self.remaining = size
                self.read_bytes = 0

            async def read(self, size: int = -1) -> bytes:
                take = self.remaining if size < 0 else min(size, self.remaining)
                self.remaining -= take
                self.read_bytes += take
                return b"x" * take

        limit = 2 * 1024 * 1024
        upload = CountingUpload(50 * 1024 * 1024)
        with self.assertRaises(Exception) as raised:
            asyncio.run(ingest_api.read_upload_within_limit(upload, max_bytes=limit, limit_mb=2))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertLessEqual(upload.read_bytes, limit + ingest_api.UPLOAD_READ_CHUNK_BYTES)
        self.assertLess(upload.read_bytes, 50 * 1024 * 1024 / 10)

    def test_admin_upload_over_the_limit_gets_413(self) -> None:
        admin, _ = make_user(role="admin")
        with patch.object(ingest_api.settings, "max_upload_size_mb", 1):
            response = client_for(admin).post(
                "/ingest/upload",
                data={"doc_type": "judgment"},
                files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10), "application/pdf")},
            )
        self.assertEqual(response.status_code, 413)


class NegativeAuthorizationTests(SecurityTestCase):
    """Every protected route refuses the wrong caller; the DB role always wins over the token's claim."""

    PROFESSIONAL = (("post", "/query/professional"), ("post", "/query/professional/pdf"), ("get", "/query/history"), ("get", "/query-history"))
    ADMIN = (
        ("get", "/admin/lawyer-applications"),
        ("get", "/admin/lawyer-applications/1"),
        ("post", "/admin/lawyer-applications/1/approve"),
        ("post", "/admin/lawyer-applications/1/reject"),
        ("post", "/admin/lawyer-applications/1/request-resubmission"),
        ("post", "/ingest/upload"),
        ("get", "/ingest/status/some-job"),
        ("get", "/ingest/corpus/stats"),
    )
    AUTHENTICATED = (("get", "/auth/me"), ("get", "/analytics/ncrb"), ("get", "/lawyer-applications/me"), ("post", "/lawyer-applications"))

    def call(self, client: TestClient, method: str, path: str):
        if method == "post":
            return client.post(path, headers={"Origin": ALLOWED_ORIGIN}, json={})
        return client.get(path)

    def test_anonymous_is_rejected_from_professional_admin_and_authenticated_routes(self) -> None:
        client = TestClient(app)
        for method, path in self.PROFESSIONAL + self.ADMIN + self.AUTHENTICATED:
            with self.subTest(path=path):
                self.assertEqual(self.call(client, method, path).status_code, 401)

    def test_lawyer_is_forbidden_from_admin_routes(self) -> None:
        lawyer, _ = make_user(role="lawyer")
        for method, path in self.ADMIN:
            with self.subTest(path=path):
                self.assertEqual(self.call(client_for(lawyer), method, path).status_code, 403)

    def test_public_user_is_forbidden_from_professional_and_admin_routes(self) -> None:
        public, _ = make_user(role="public")
        for method, path in self.PROFESSIONAL + self.ADMIN:
            with self.subTest(path=path):
                self.assertEqual(self.call(client_for(public), method, path).status_code, 403)

    def test_inactive_user_is_rejected_from_every_authenticated_route(self) -> None:
        admin, _ = make_user(role="admin", active=False)
        for method, path in self.PROFESSIONAL + self.ADMIN + self.AUTHENTICATED:
            with self.subTest(path=path):
                self.assertEqual(self.call(client_for(admin), method, path).status_code, 401)

    def test_expired_and_tampered_tokens_are_rejected(self) -> None:
        lawyer, _ = make_user(role="lawyer")
        expired = client_for(lawyer, expires=timedelta(seconds=-5))
        self.assertEqual(expired.get("/auth/me").status_code, 401)
        tampered = TestClient(app)
        token = create_access_token({"sub": str(lawyer.id), "email": lawyer.email, "role": "lawyer"})
        header, payload, signature = token.split(".")
        tampered.cookies.set(COOKIE_NAME, f"{header}.{payload}.{signature[:-4]}AAAA")
        self.assertEqual(tampered.get("/auth/me").status_code, 401)
        forged = TestClient(app)
        import jwt as pyjwt

        forged.cookies.set(COOKIE_NAME, pyjwt.encode({"sub": str(lawyer.id), "role": "admin"}, "attacker-chosen-secret-0123456789abcdef", algorithm="HS256"))
        self.assertEqual(forged.get("/auth/me").status_code, 401)

    def test_role_claim_in_token_never_overrides_the_database_role(self) -> None:
        public, _ = make_user(role="public")
        lawyer, _ = make_user(role="lawyer")
        self.assertEqual(client_for(public, role_claim="lawyer").get("/query/history").status_code, 403)
        self.assertEqual(client_for(lawyer, role_claim="admin").get("/admin/lawyer-applications").status_code, 403)
        me = client_for(lawyer, role_claim="admin").get("/auth/me").json()
        self.assertEqual(me["role"], "lawyer")

    def test_user_a_cannot_see_user_b_history_or_lawyer_application(self) -> None:
        lawyer_a, _ = make_user(role="lawyer")
        lawyer_b, _ = make_user(role="lawyer")
        public_b, _ = make_user(role="public")
        db = SessionLocal()
        try:
            db.add(QueryHistory(user_id=lawyer_b.id, query_text="B's private query", mode="professional", response_json={}))
            application = LawyerVerificationApplication(
                user_id=public_b.id, bar_council="Kerala", enrollment_number=f"K/{secrets.token_hex(3)}", enrollment_year=2020,
                jurisdiction="Kerala", proof_file_name="proof.pdf", proof_content_type="application/pdf",
                proof_storage_key=f"{secrets.token_hex(8)}.pdf", status="PENDING",
            )
            db.add(application)
            db.commit()
            application_id = application.id
        finally:
            db.close()
        history = client_for(lawyer_a).get("/query/history")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn("B's private query", history.text)
        self.assertEqual(client_for(lawyer_a).get(f"/admin/lawyer-applications/{application_id}").status_code, 403)
        own = client_for(lawyer_a).get("/lawyer-applications/me")
        self.assertEqual(own.status_code, 200)
        self.assertNotIn(str(application_id), str((own.json() or {}).get("application") or ""))
        self.assertIn("B's private query", client_for(lawyer_b).get("/query/history").text)


if __name__ == "__main__":
    unittest.main()
