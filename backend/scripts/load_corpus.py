"""Load the curated trusted-judgment corpus into PostgreSQL ``documents`` and ``chunks`` (step 20; README "Corpus").

Sources (the same as the indexes): ``data/structured/manifests/trusted_judgment_processing_manifest.json`` (committed)
and the chunk files in ``data/processed/judgment_chunks/*.json`` (gitignored: real judgment text; team members copy
them from the shared project folder, see README.md).

Before writing anything it checks that the chunk files are exactly the curated corpus: their chunk-universe
fingerprint (``bm25.chunk_universe_fingerprint``: chunk IDs, document IDs, text hashes and processing versions) must
equal the one recorded in ``data/structured/manifests/trusted_judgment_lexical_index_summary.json``.

The rows are built and written by ``reconcile_backfill.py``'s ``plan``/``execute`` (unchanged), so a fresh database
gets exactly the rows the development database has. That legacy script is pinned to revision 0005; this one requires
the current Alembic head instead. Existing rows must match exactly or nothing is written; a second run makes 0 changes.
The outcome columns (``case_disposition``, ``conviction_status``, ``appeal_result``) are inserted as NULL and not
compared: ``produce_analytics_data.py`` fills them after this load (README "Quick start").

Usage:
    .venv/bin/python backend/scripts/load_corpus.py --database-url-env DATABASE_URL [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval.bm25 import chunk_universe_fingerprint  # noqa: E402
from backend.scripts import reconcile_backfill  # noqa: E402
from backend.scripts import reconcile_inventory as inventory_lib  # noqa: E402
from backend.scripts.reconcile_common import REPO_ROOT, alembic_version, connect, resolve_database  # noqa: E402

OUTCOME_COLUMNS = ("case_disposition", "conviction_status", "appeal_result")
LEXICAL_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_lexical_index_summary.json"


def alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_current_head()


def check_chunk_files() -> dict[str, int | str]:
    """The chunk files must be the curated corpus the indexes were built from."""
    documents, chunks = inventory_lib.load_curated_corpus()
    if not chunks:
        raise SystemExit(
            f"refused: no chunk files in {inventory_lib.CHUNK_DIR.relative_to(REPO_ROOT)}; copy them from the shared "
            "project folder (README.md, \"Corpus\")"
        )
    expected = json.loads(LEXICAL_SUMMARY.read_text(encoding="utf-8"))
    rows = sorted(chunks.values(), key=lambda row: row["chunk_id"])
    fingerprint = chunk_universe_fingerprint(rows)
    if fingerprint != expected["chunk_universe_fingerprint"] or len(rows) != expected["chunk_count"]:
        raise SystemExit(
            f"refused: the chunk files ({len(rows)} chunks, fingerprint {fingerprint[:12]}…) are not the curated corpus "
            f"({expected['chunk_count']} chunks, fingerprint {expected['chunk_universe_fingerprint'][:12]}…)"
        )
    missing = sorted({row["document_id"] for row in rows} - set(documents))
    if missing:
        raise SystemExit(f"refused: chunks for documents not in the processing manifest: {missing[:5]}")
    return {"documents": len(documents), "chunks": len(rows), "fingerprint": fingerprint}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)

    corpus = check_chunk_files()
    print(f"curated corpus: {corpus['documents']} documents, {corpus['chunks']} chunks, fingerprint {corpus['fingerprint']}")
    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=not args.dry_run)
    head = alembic_head()
    connection = connect(url, readonly=args.dry_run)
    try:
        with connection.cursor() as cursor:
            revision = alembic_version(cursor)
            if revision != head:
                raise SystemExit(f"refused: database '{database}' is at revision {revision}; run alembic upgrade head ({head}) first")
            work = reconcile_backfill.plan(cursor, ignore_document_columns=OUTCOME_COLUMNS)
            verb = "WOULD INSERT" if args.dry_run else "INSERTING"
            print(f"target database: {database}")
            print(f"  {verb} documents: {len(work['insert_documents'])}, chunks: {len(work['insert_chunks'])}")
            print(f"  unchanged: {work['unchanged_documents']} documents, {work['unchanged_chunks']} chunks")
            if work["conflicts"]:
                for conflict in work["conflicts"]:
                    print(f"  CONFLICT {conflict}")
                connection.rollback()
                print("aborted: existing rows differ from the curated sources; nothing written")
                return 1
            changes = len(work["insert_documents"]) + len(work["insert_chunks"])
            if args.dry_run:
                connection.rollback()
                print(f"dry run: {changes} changes would be made")
                return 0
            reconcile_backfill.execute(cursor, work)
        connection.commit()
        print(f"changes: {changes}")
        return 0
    finally:
        if not connection.closed:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
