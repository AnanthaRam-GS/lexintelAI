"""Step 20: DATABASE_URL has no default; without it the backend (and Alembic) refuse to start outside APP_ENV=test."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings  # noqa: E402


def run(code: list[str], **env: str) -> subprocess.CompletedProcess:
    # A directory without .env, and no DATABASE_URL in the environment.
    base = {key: value for key, value in os.environ.items() if key not in {"DATABASE_URL", "APP_ENV", "TEST_DATABASE_URL"}}
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(code, cwd=cwd, env={**base, "PYTHONPATH": str(REPO_ROOT), **env}, capture_output=True, text=True, timeout=120)


class DatabaseUrlDefaultTests(unittest.TestCase):
    def test_there_is_no_placeholder_default(self) -> None:
        self.assertEqual(Settings.model_fields["database_url"].default, "")

    def test_the_app_refuses_to_start_without_it_outside_test(self) -> None:
        for env in ("development", "production"):
            with self.subTest(app_env=env):
                completed = run([sys.executable, "-c", "import backend.main"], APP_ENV=env, JWT_SECRET_KEY="k" * 48)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("MissingConfigurationError: DATABASE_URL is not set", completed.stderr)
                self.assertNotIn("user:password", completed.stderr)

    def test_test_mode_imports_with_an_unconnectable_url(self) -> None:
        completed = run(
            [sys.executable, "-c", "from backend.app.db import session; print(session.engine.url.host)"], APP_ENV="test"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "unconfigured.invalid")

    def test_alembic_refuses_without_it(self) -> None:
        completed = run([sys.executable, "-m", "alembic", "-c", str(REPO_ROOT / "alembic.ini"), "current"], APP_ENV="development")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("DATABASE_URL is not set", completed.stderr)


if __name__ == "__main__":
    unittest.main()
