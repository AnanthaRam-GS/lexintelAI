"""Step 20b: APP_ENV has no default, console email is refused in production, BACKEND_HOST defaults to loopback.

The startup cases run the real app (lifespan included) in a fresh interpreter, in a directory without .env, with a
database URL that is never connected to: each check refuses before the database is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.startup_checks import (  # noqa: E402
    InsecureConfigurationError,
    validate_app_env,
    validate_email_delivery,
)

UNCONNECTABLE_DATABASE_URL = "postgresql://unconfigured.invalid:5432/legalai_unconfigured"
STRIPPED = ("APP_ENV", "DATABASE_URL", "TEST_DATABASE_URL", "EMAIL_DELIVERY_MODE", "BACKEND_HOST", "LEGALAI_E2E")


def bare_settings(**values: str) -> Settings:
    """Settings from these values only: no .env and none of the variables under test from the environment."""
    clean = {key: value for key, value in os.environ.items() if not key.startswith(STRIPPED)}
    with mock.patch.dict(os.environ, clean, clear=True):
        return Settings(_env_file=None, **values)


def start_app(**env: str) -> subprocess.CompletedProcess:
    """Import backend.main and run its lifespan (startup checks), with exactly these settings."""
    base = {key: value for key, value in os.environ.items() if not key.startswith(STRIPPED)}
    code = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        import backend.main
        with TestClient(backend.main.app):
            print("STARTED")
        """
    )
    settings = {"DATABASE_URL": UNCONNECTABLE_DATABASE_URL, "JWT_SECRET_KEY": "k" * 48, "LEGALAI_MODEL_WARMUP": "false", **env}
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(
            [sys.executable, "-c", code], cwd=cwd, env={**base, "PYTHONPATH": str(REPO_ROOT), **settings},
            capture_output=True, text=True, timeout=180,
        )


class AppEnvTests(unittest.TestCase):
    def test_there_is_no_default(self) -> None:
        self.assertEqual(Settings.model_fields["app_env"].default, "")
        self.assertEqual(bare_settings().app_env, "")

    def test_unset_or_unknown_is_refused(self) -> None:
        for value, message in (("", "APP_ENV is not set"), ("   ", "APP_ENV is not set"), ("staging", "not a known environment")):
            with self.subTest(app_env=value), self.assertRaisesRegex(InsecureConfigurationError, message):
                validate_app_env(bare_settings(app_env=value))
        for value in ("development", "test", "production", "Production "):
            validate_app_env(bare_settings(app_env=value))

    def test_startup_refuses_without_it(self) -> None:
        completed = start_app()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("InsecureConfigurationError: APP_ENV is not set", completed.stderr)
        self.assertNotIn("STARTED", completed.stdout)


class ConsoleEmailInProductionTests(unittest.TestCase):
    def test_console_is_refused_only_in_production(self) -> None:
        with self.assertRaisesRegex(InsecureConfigurationError, "EMAIL_DELIVERY_MODE=console is refused"):
            validate_email_delivery(bare_settings(app_env="production", email_delivery_mode=" Console "))
        validate_email_delivery(bare_settings(app_env="production", email_delivery_mode="smtp"))
        for env in ("development", "test"):
            validate_email_delivery(bare_settings(app_env=env, email_delivery_mode="console"))

    def test_startup_refuses_console_in_production(self) -> None:
        completed = start_app(APP_ENV="production", EMAIL_DELIVERY_MODE="console")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("InsecureConfigurationError: EMAIL_DELIVERY_MODE=console is refused with APP_ENV=production", completed.stderr)
        self.assertNotIn("STARTED", completed.stdout)


class BackendHostTests(unittest.TestCase):
    def test_default_is_loopback(self) -> None:
        self.assertEqual(Settings.model_fields["backend_host"].default, "127.0.0.1")
        self.assertEqual(bare_settings().backend_host, "127.0.0.1")

    def test_an_explicit_value_is_kept(self) -> None:
        self.assertEqual(bare_settings(backend_host="0.0.0.0").backend_host, "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
