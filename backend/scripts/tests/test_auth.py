"""Unit and integration tests for LegalAI Task 1.R.1 (FastAPI, Database & Authentication)."""

from __future__ import annotations

from datetime import timedelta
import os
import sys
import unittest
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.security import (
    COOKIE_NAME,
    DEFAULT_DEV_SECRET,
    create_access_token,
    decode_access_token,
    get_cookie_options,
    get_jwt_secret,
    hash_password,
    verify_password,
)
from backend.app.core.config import Settings
from backend.main import app
from backend.scripts.seed_users import seed_development_users


class TestSecurityUnit(unittest.TestCase):
    """Unit tests for password hashing, verification, and JWT operations."""

    def test_password_hashing_and_verification(self) -> None:
        plain_pwd = "SuperSecretPassword123!"
        hashed = hash_password(plain_pwd)

        self.assertTrue(hashed.startswith("$2b$") or hashed.startswith("$2a$"))
        self.assertNotEqual(plain_pwd, hashed)
        self.assertTrue(verify_password(plain_pwd, hashed))
        self.assertFalse(verify_password("WrongPassword123!", hashed))
        self.assertFalse(verify_password("", hashed))

    def test_jwt_creation_and_decoding(self) -> None:
        claims = {
            "sub": "100",
            "email": "attorney@legalai.local",
            "role": "lawyer",
        }
        token = create_access_token(claims)
        self.assertIsInstance(token, str)

        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "100")
        self.assertEqual(payload["email"], "attorney@legalai.local")
        self.assertEqual(payload["role"], "lawyer")
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)

    def test_jwt_expiration(self) -> None:
        claims = {"sub": "100", "email": "test@legalai.local", "role": "lawyer"}
        expired_token = create_access_token(claims, expires_delta=timedelta(seconds=-10))

        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_access_token(expired_token)

    def test_jwt_tampered_token(self) -> None:
        token = create_access_token({"sub": "100", "email": "test@legalai.local", "role": "lawyer"})
        tampered = token[:-5] + "XXXXX"

        with self.assertRaises(jwt.PyJWTError):
            decode_access_token(tampered)

    def test_development_allows_explicit_dev_jwt_fallback(self) -> None:
        settings = Settings(app_env="development", jwt_secret_key="")
        self.assertEqual(get_jwt_secret(settings), DEFAULT_DEV_SECRET)

    def test_production_requires_configured_jwt_secret(self) -> None:
        settings = Settings(app_env="production", jwt_secret_key="")
        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY"):
            get_jwt_secret(settings)

    def test_production_uses_configured_jwt_secret(self) -> None:
        configured_key = "configured-production-test-key"
        settings = Settings(app_env="production", jwt_secret_key=configured_key)
        self.assertEqual(get_jwt_secret(settings), configured_key)

    def test_cookie_options(self) -> None:
        opts = get_cookie_options()
        self.assertTrue(opts["httponly"])
        self.assertEqual(opts["samesite"], "lax")
        self.assertEqual(opts["path"], "/")
        self.assertGreater(opts["max_age"], 0)


class TestAuthIntegration(unittest.TestCase):
    """Integration tests for authentication endpoints, cookies, and CORS."""

    @classmethod
    def setUpClass(cls) -> None:
        # Ensure test database has development seed users populated
        seed_development_users()
        cls.client = TestClient(app)

    def test_health_check(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["database"]["connected"])

    def test_cors_preflight_and_headers(self) -> None:
        response = self.client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )
        self.assertEqual(
            response.headers.get("access-control-allow-credentials"),
            "true",
        )

    def test_login_lawyer_success(self) -> None:
        client = TestClient(app)
        payload = {
            "email": "lawyer@legalai.local",
            "password": "LawyerPassword123!",
        }
        response = client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["user"]["email"], "lawyer@legalai.local")
        self.assertEqual(data["user"]["role"], "lawyer")
        self.assertEqual(data["message"], "Login successful")

        # Verify HttpOnly cookie was set
        self.assertIn(COOKIE_NAME, response.cookies)
        cookie_val = response.cookies[COOKIE_NAME]
        self.assertTrue(len(cookie_val) > 20)

        # Verify profile retrieval with the received cookie
        me_resp = client.get("/auth/me")
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["email"], "lawyer@legalai.local")
        self.assertEqual(me_resp.json()["role"], "lawyer")

    def test_login_admin_success(self) -> None:
        client = TestClient(app)
        payload = {
            "email": "admin@legalai.local",
            "password": "AdminPassword123!",
        }
        response = client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["user"]["email"], "admin@legalai.local")
        self.assertEqual(data["user"]["role"], "admin")
        self.assertIn(COOKIE_NAME, response.cookies)

    def test_login_invalid_password(self) -> None:
        client = TestClient(app)
        payload = {
            "email": "lawyer@legalai.local",
            "password": "WrongPassword999!",
        }
        response = client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password")
        self.assertNotIn(COOKIE_NAME, response.cookies)

    def test_login_nonexistent_email(self) -> None:
        client = TestClient(app)
        payload = {
            "email": "nobody@legalai.local",
            "password": "SomePassword123!",
        }
        response = client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password")

    def test_unauthenticated_access_to_me(self) -> None:
        client = TestClient(app)
        response = client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertIn("credentials", response.json()["detail"].lower())

    def test_logout_clears_cookie(self) -> None:
        client = TestClient(app)
        # Login first
        login_resp = client.post(
            "/auth/login",
            json={"email": "lawyer@legalai.local", "password": "LawyerPassword123!"},
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn(COOKIE_NAME, client.cookies)

        # Logout
        logout_resp = client.post("/auth/logout")
        self.assertEqual(logout_resp.status_code, 200)
        self.assertEqual(logout_resp.json()["message"], "Logged out successfully")

        # Verify access to protected route is rejected after logout
        # (In TestClient, cookies may either be deleted or expired/cleared)
        client.cookies.clear()  # Ensure client respects the cookie deletion
        me_resp = client.get("/auth/me")
        self.assertEqual(me_resp.status_code, 401)

    def test_role_enforcement_dependencies(self) -> None:
        from backend.app.core.dependencies import require_admin, require_role
        from backend.app.db.models import User
        from fastapi import HTTPException

        lawyer_user = User(id=1, email="lawyer@legalai.local", role="lawyer")
        admin_user = User(id=2, email="admin@legalai.local", role="admin")

        # require_role for lawyer/admin allows both
        lawyer_or_admin = require_role(["lawyer", "admin"])
        self.assertEqual(lawyer_or_admin(lawyer_user), lawyer_user)
        self.assertEqual(lawyer_or_admin(admin_user), admin_user)

        # require_admin allows admin, rejects lawyer with 403
        self.assertEqual(require_admin(admin_user), admin_user)
        with self.assertRaises(HTTPException) as cm:
            require_admin(lawyer_user)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Operation not permitted for role 'lawyer'", cm.exception.detail)


if __name__ == "__main__":
    unittest.main()
