"""Prepare a database and a state directory for a browser end-to-end run (step 17; docs/TESTING.md).

Fake mode (CI): migrate an empty ``*_e2e`` database, then
- load the synthetic fixture corpus (backend/scripts/tests/fixtures/corpus) into ``documents``/``chunks``, Chroma
  (``<state>/chroma_store``, hashing embedder) and BM25 (``<state>/bm25_store``), so the three stores agree;
- load analytics data from the committed IPC-BNS and NCRB CSVs and run the analytics producer over the fixture text;
- render the upload fixtures (the synthetic FIR, and a synthetic judgment with a per-run line) into ``<state>/files``.

Real mode (local): the database is ``legalai_rehearsal`` restored from a backup and the stores are copies of the dev
stores; nothing is loaded but the test accounts and the upload fixtures.

Both modes create the test accounts (an admin and a lawyer) with passwords generated now, written only to
``<state>/accounts.json`` (mode 600). Nothing is printed but counts.

Refuses: APP_ENV other than test; the development database; a database not named ``*_e2e`` or
``legalai_rehearsal``; a state directory that is or contains the repository's own stores.

Usage:
    APP_ENV=test DATABASE_URL=... .venv/bin/python -m backend.scripts.e2e.setup_e2e --state-dir <dir> [--mode real]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.reconcile_common import TargetRefused, check_store_paths, resolve_database  # noqa: E402

ALLOWED_DATABASES = ("legalai_rehearsal",)
INGEST_FIXTURE = REPO_ROOT / "backend/scripts/tests/fixtures/e2e/ingest_judgment_synthetic.txt"
ACCOUNTS = {"admin": "E2E Admin", "lawyer": "E2E Lawyer"}


def check_target(state_dir: Path) -> str:
    if (os.environ.get("APP_ENV") or "").strip().lower() != "test":
        raise TargetRefused("APP_ENV must be test for an end-to-end setup")
    _url, name = resolve_database("DATABASE_URL", confirm_dev=False, write=True)
    if not (name.endswith("_e2e") or name in ALLOWED_DATABASES):
        raise TargetRefused(f"database '{name}' is not an end-to-end database (*_e2e or {', '.join(ALLOWED_DATABASES)})")
    check_store_paths([state_dir], confirm_dev=False, write=True)
    for store in ("chroma_store", "bm25_store"):
        if (REPO_ROOT / store).resolve() in state_dir.resolve().parents:
            raise TargetRefused("the state directory must not be inside the repository's stores")
    return name


def migrate() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=REPO_ROOT, check=True, stdout=subprocess.DEVNULL)


def truncate_all(engine: Any) -> None:
    from sqlalchemy import text

    from backend.app.db.base import Base
    import backend.app.db.models  # noqa: F401

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def load_fixture_corpus(db: Any, state_dir: Path) -> dict[str, int]:
    """documents/chunks rows, Chroma and BM25 from the same fixture chunks (as reconcile_backfill shapes them)."""
    from backend.app.core.config import Settings, resolve_chroma_location
    from backend.app.db.models import Chunk, Document
    from backend.app.services.retrieval.bm25 import DEFAULT_INDEX_NAME, Bm25LexicalIndex
    from backend.app.testing.fake_providers import HashingEmbedder
    from backend.scripts.build_vector_index import build_index
    from backend.scripts.tests.fixture_corpus import fixture_chunks, fixture_documents

    chunks = fixture_chunks()
    for source in fixture_documents():
        document = Document(
            doc_type="judgment",
            case_name=source["case_title"],
            court_name=source["court"]["court_name"],
            court_level=source["court"]["court_level"],
            decision_date=date.fromisoformat(source["decision_date"]),
            year=source["decision_year"],
            source_url=source["source_url"],
            checksum=source["sha256"],
            source_document_key=source["document_id"],
        )
        db.add(document)
        db.flush()
        for chunk in (row for row in chunks if row["document_id"] == source["document_id"]):
            db.add(Chunk(
                document_id=document.id,
                chunk_index=chunk["chunk_index"],
                text=chunk["chunk_text"],
                chroma_id=chunk["chunk_id"],
                token_count=chunk["estimated_token_count"],
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                paragraph_start=chunk["paragraph_start"],
                paragraph_end=chunk["paragraph_end"],
            ))
    db.commit()
    chroma_dir, collection = resolve_chroma_location(Settings())
    if state_dir.resolve() not in chroma_dir.resolve().parents:
        raise TargetRefused("CHROMA_PERSIST_DIR must be inside the state directory")
    vector = build_index(chunks, HashingEmbedder(), chroma_dir, collection, rebuild=True, store_kind="chroma")
    if vector["failed"]:
        raise RuntimeError(f"vector index build failed for {vector['failed']} chunks")
    lexical = Bm25LexicalIndex(state_dir / "bm25_store", DEFAULT_INDEX_NAME).build(chunks, rebuild=True)
    return {"documents": len(fixture_documents()), "chunks": len(chunks), "vectors": vector["final_collection_count"],
            "bm25_records": lexical["indexed_chunks"]}


def load_analytics(db: Any) -> dict[str, Any]:
    from backend.scripts.load_ipc_bns import load_ipc_bns_mapping
    from backend.scripts.load_ncrb import load_ncrb_stats
    from backend.scripts.produce_analytics_data import produce

    mapping = load_ipc_bns_mapping(db)
    ncrb_mapping = load_ipc_bns_mapping(db, source="NCRB_CII_2024_T1A4")  # PDF-printed pairs (step 19b)
    ncrb = load_ncrb_stats(db)
    produced = produce(db, dry_run=False)
    db.commit()
    return {"ipc_bns_rows": mapping.get("inserted"), "ipc_bns_ncrb_rows": ncrb_mapping.get("inserted"), "ncrb_rows": ncrb.get("inserted"), "sections": dict(produced.get("sections", {}))}


def write_accounts(db: Any, state_dir: Path) -> None:
    from backend.app.core.security import hash_password
    from backend.app.db.models import User

    accounts = {}
    for role, name in ACCOUNTS.items():
        email = f"e2e-{role}@legalai.test"
        password = secrets.token_urlsafe(18)
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, full_name=name, hashed_password=hash_password(password), role=role, email_verified=1)
            db.add(user)
        else:
            user.hashed_password, user.role, user.email_verified, user.is_active = hash_password(password), role, 1, 1
        accounts[role] = {"email": email, "password": password}
    db.commit()
    path = state_dir / "accounts.json"
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(accounts), encoding="utf-8")


def text_pdf(text: str, path: Path) -> Path:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=9, fontname="helv")
    document.save(path)
    document.close()
    return path


def write_upload_fixtures(state_dir: Path) -> None:
    from backend.scripts.tests.brief_fixtures import write_fixture_pdf

    files = state_dir / "files"
    files.mkdir(parents=True, exist_ok=True)
    write_fixture_pdf("fir", files)
    # A per-run line, so the first upload is new even against a store that kept an earlier run's ingest.
    text = INGEST_FIXTURE.read_text(encoding="utf-8") + f"\nRun reference: {secrets.token_hex(8)}\n"
    text_pdf(text, files / "ingest_judgment_synthetic.pdf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("fake", "real"), default="fake")
    args = parser.parse_args(argv)
    state_dir = args.state_dir.resolve()
    try:
        database = check_target(state_dir)
    except TargetRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    state_dir.mkdir(parents=True, exist_ok=True)
    migrate()
    from backend.app.db import session as db_session

    if db_session.engine.url.database != database:
        raise TargetRefused("the application engine is bound to a different database")
    summary: dict[str, Any] = {"database": database, "mode": args.mode}
    if args.mode == "fake":
        truncate_all(db_session.engine)
    db = db_session.SessionLocal()
    try:
        if args.mode == "fake":
            summary["corpus"] = load_fixture_corpus(db, state_dir)
            summary["analytics"] = load_analytics(db)
        write_accounts(db, state_dir)
    finally:
        db.close()
    write_upload_fixtures(state_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
