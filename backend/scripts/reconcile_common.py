"""Shared safety helpers for the reconciliation scripts.

The cleanup, backfill and consistency scripts take an explicit target:
- the database through ``--database-url-env NAME``: the URL is read from that
  environment variable, so it never appears in shell history or ``ps``, and
  only the database name is printed;
- the stores through explicit ``--chroma-dir`` / ``--bm25-file`` paths.

Writing to the development database (the one named by ``DATABASE_URL`` in the
repository ``.env``) or to the repository's real ``chroma_store/`` /
``bm25_store/`` requires ``--confirm-dev``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_STORE_DIRS = (REPO_ROOT / "chroma_store", REPO_ROOT / "bm25_store")

# ON DELETE rules the cleanup relies on, verified against the live catalog
# before anything is deleted: (table, column, referenced table) -> rule.
EXPECTED_FK_RULES = {
    ("chunks", "document_id", "documents"): "CASCADE",
    ("document_sections", "document_id", "documents"): "CASCADE",
    ("ingestion_jobs", "document_id", "documents"): "SET NULL",
    ("query_history", "user_id", "users"): "SET NULL",
    ("email_verification_tokens", "user_id", "users"): "CASCADE",
    ("email_verification_otps", "user_id", "users"): "CASCADE",
    ("lawyer_verification_applications", "user_id", "users"): "CASCADE",
    ("lawyer_verification_applications", "reviewed_by", "users"): "SET NULL",
}


class TargetRefused(SystemExit):
    """Raised (as a non-zero exit) when a target is unsafe without confirmation."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/").split("?", 1)[0]


def dev_database_name() -> str | None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DATABASE_URL" and value.strip():
            return database_name(value.strip().strip("'\""))
    return None


def resolve_database(url_env: str, *, confirm_dev: bool, write: bool) -> tuple[str, str]:
    """Return (url, database name) from the named environment variable."""
    url = os.environ.get(url_env, "").strip()
    if not url:
        raise TargetRefused(f"environment variable {url_env} is not set")
    name = database_name(url)
    if write and name == dev_database_name() and not confirm_dev:
        raise TargetRefused(f"database '{name}' is the development database; pass --confirm-dev to write to it")
    return url, name


def check_store_paths(paths: list[Path], *, confirm_dev: bool, write: bool) -> None:
    for path in paths:
        resolved = path.resolve()
        for store in DEV_STORE_DIRS:
            if write and (resolved == store or store in resolved.parents) and not confirm_dev:
                raise TargetRefused(f"{path} is inside the repository's {store.name}/; pass --confirm-dev to modify it")


def connect(url: str, *, readonly: bool) -> Any:
    import psycopg2

    connection = psycopg2.connect(url)
    connection.set_session(readonly=readonly, autocommit=False)
    return connection


def verify_fk_rules(cursor: Any) -> None:
    cursor.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text,
               CASE c.confdeltype WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL'
                    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'd' THEN 'SET DEFAULT' END
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f'
        """
    )
    actual = {(table, column, referenced): rule for table, column, referenced, rule in cursor.fetchall()}
    wrong = {key: actual.get(key) for key, rule in EXPECTED_FK_RULES.items() if actual.get(key) != rule}
    if wrong:
        details = ", ".join(f"{t}.{c}->{r}: expected {EXPECTED_FK_RULES[(t, c, r)]}, found {v}" for (t, c, r), v in wrong.items())
        raise SystemExit(f"refused: foreign-key ON DELETE rules differ from what the cleanup relies on: {details}")


def alembic_version(cursor: Any) -> str | None:
    cursor.execute("SELECT version_num FROM alembic_version")
    row = cursor.fetchone()
    return row[0] if row else None
