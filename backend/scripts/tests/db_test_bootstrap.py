"""Isolated-database bootstrap for LegalAI database-backed test modules.

Import this module before any other ``backend`` import in a DB-backed test
module. It must run before ``backend.main``, ``backend.app.db.session`` or
``Settings`` are imported, because the SQLAlchemy engine is created from
``DATABASE_URL`` at import time.

On import it:

1. Requires ``TEST_DATABASE_URL`` and aborts, before any database connection,
   if it is unset, its database name does not end in ``_test``, or it names
   the development database (from ``.env`` or a pre-set ``DATABASE_URL``).
2. Sets ``DATABASE_URL`` from it, blanks provider/SMTP credentials, forces
   console email delivery and offline Hugging Face access, and blocks
   ``urllib`` network calls and SMTP connections.
3. Redirects Chroma, BM25, ingestion-upload and lawyer-verification storage to
   a per-process temporary directory.
4. Blocks real BGE-M3 / BGE reranker construction unless
   ``LEGALAI_ALLOW_MODEL_LOADING=1``, so no test silently pulls large models.
5. Runs ``alembic upgrade head`` against the test database (in a subprocess,
   so Alembic's logging config cannot disable the test process's loggers).

Modules then call ``isolate_test_cases(globals())`` at the end so every test
starts from truncated tables (with class fixtures re-run), and the module ends
with the tables truncated. Transaction rollback is not used because the code
under test opens its own ``SessionLocal`` sessions, commits, and runs FastAPI
background tasks, none of which a test-owned outer transaction can contain.

Run ``python -m backend.scripts.tests.db_test_bootstrap`` to validate the
configuration and migrate the test database without running tests.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import smtplib
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_DATABASE_SUFFIX = "_test"
BLANKED_CREDENTIAL_VARIABLES = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "INDIAN_KANOON_API_TOKEN",
    "SMTP_PASSWORD",
)


class TestDatabaseConfigurationError(RuntimeError):
    """Raised when the test database configuration is unsafe to use."""


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/").split("?", 1)[0]


def development_database_names() -> set[str]:
    names: set[str] = set()
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL" and value.strip():
                names.add(database_name(value.strip().strip("'\"")))
    preset = os.environ.get("DATABASE_URL", "").strip()
    if preset and preset != os.environ.get("TEST_DATABASE_URL", "").strip():
        names.add(database_name(preset))
    return names


def validated_test_database_url() -> str:
    """Return TEST_DATABASE_URL, or raise without connecting to anything."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise TestDatabaseConfigurationError(
            "TEST_DATABASE_URL is not set. DB-backed tests refuse to run without an isolated test database."
        )
    name = database_name(url)
    if not name.endswith(TEST_DATABASE_SUFFIX):
        raise TestDatabaseConfigurationError(
            f"TEST_DATABASE_URL names database '{name}', which does not end in '{TEST_DATABASE_SUFFIX}'."
        )
    if name in development_database_names():
        raise TestDatabaseConfigurationError(
            f"TEST_DATABASE_URL names database '{name}', which is the development database."
        )
    session_module = sys.modules.get("backend.app.db.session")
    if session_module is not None and session_module.engine.url.database != name:
        raise TestDatabaseConfigurationError(
            "backend.app.db.session was imported before the test bootstrap and is bound to "
            f"database '{session_module.engine.url.database}'. Run DB-backed modules in their own process."
        )
    return url


TEST_DATABASE_URL = validated_test_database_url()
TEST_DATABASE_NAME = database_name(TEST_DATABASE_URL)

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="legalai_db_tests_"))
atexit.register(shutil.rmtree, TEMP_ROOT, ignore_errors=True)
TEMP_CHROMA_DIR = TEMP_ROOT / "chroma_store"
TEMP_BM25_DIR = TEMP_ROOT / "bm25_store"
TEMP_UPLOAD_DIR = TEMP_ROOT / "uploads"
TEMP_VERIFICATION_DIR = TEMP_ROOT / "lawyer_verification"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CHROMA_PERSIST_DIR"] = str(TEMP_CHROMA_DIR)
os.environ["VERIFICATION_DOCUMENT_DIR"] = str(TEMP_VERIFICATION_DIR)
os.environ["EMAIL_DELIVERY_MODE"] = "console"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
for variable in BLANKED_CREDENTIAL_VARIABLES:
    os.environ[variable] = ""


def _network_disabled(*_args, **_kwargs):
    raise RuntimeError("Network access is disabled by the LegalAI DB test bootstrap.")


# Tests that need HTTP or SMTP behaviour patch these explicitly with mocks.
urllib.request.urlopen = _network_disabled
smtplib.SMTP = _network_disabled
smtplib.SMTP_SSL = _network_disabled


def migrate_test_database() -> None:
    """Apply all Alembic migrations to the test database."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TestDatabaseConfigurationError(
            f"alembic upgrade head failed for database '{TEST_DATABASE_NAME}':\n{result.stderr[-2000:]}"
        )


migrate_test_database()

from backend.app.db import session as db_session  # noqa: E402

if db_session.engine.url.database != TEST_DATABASE_NAME:
    raise TestDatabaseConfigurationError(
        f"SQLAlchemy engine is bound to '{db_session.engine.url.database}', not '{TEST_DATABASE_NAME}'."
    )

from backend.app.api import ingest as ingest_api  # noqa: E402
from backend.app.api import query as query_api  # noqa: E402
from backend.app.db.base import Base  # noqa: E402
import backend.app.db.models  # noqa: E402,F401
from backend.scripts import build_lexical_index, build_vector_index  # noqa: E402

ingest_api.UPLOAD_DIR = TEMP_UPLOAD_DIR
query_api.BM25_PERSIST_DIR = TEMP_BM25_DIR
query_api.CHROMA_PERSIST_DIR = TEMP_CHROMA_DIR
query_api.clear_retrieval_service_cache()
build_lexical_index.DEFAULT_PERSIST_DIR = TEMP_BM25_DIR
build_vector_index.DEFAULT_PERSIST_DIR = TEMP_CHROMA_DIR

if os.environ.get("LEGALAI_ALLOW_MODEL_LOADING") != "1":
    from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
    from backend.app.services.reranking.bge import BgeReranker

    def _model_loading_disabled(self, *_args, **_kwargs):
        raise RuntimeError(
            f"{type(self).__name__} model loading is disabled in DB tests; set LEGALAI_ALLOW_MODEL_LOADING=1 to allow it."
        )

    BgeM3EmbeddingProvider.__init__ = _model_loading_disabled
    BgeReranker.__init__ = _model_loading_disabled


def truncate_all_tables() -> None:
    """Empty every application table in the test database."""
    if db_session.engine.url.database != TEST_DATABASE_NAME:
        raise TestDatabaseConfigurationError("Refusing to truncate a database other than the test database.")
    from sqlalchemy import text

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with db_session.engine.begin() as connection:
        # Fail loudly instead of hanging if a leaked session still holds a lock.
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def _isolate(test_case: type[unittest.TestCase]) -> None:
    original_set_up = test_case.setUp
    overrides_class_fixture = test_case.setUpClass.__func__ is not unittest.TestCase.setUpClass.__func__
    class_fixture = test_case.setUpClass

    def set_up(self: unittest.TestCase) -> None:
        truncate_all_tables()
        if overrides_class_fixture:
            class_fixture()
        original_set_up(self)

    test_case.setUp = set_up


def isolate_test_cases(namespace: dict) -> None:
    """Give every TestCase defined in a module a clean database per test."""
    module_name = namespace["__name__"]
    for value in list(namespace.values()):
        if isinstance(value, type) and issubclass(value, unittest.TestCase) and value.__module__ == module_name:
            _isolate(value)
    namespace.setdefault("tearDownModule", truncate_all_tables)


if __name__ == "__main__":
    print(f"Test database '{TEST_DATABASE_NAME}' validated and migrated to head.")
