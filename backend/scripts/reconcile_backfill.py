"""Backfill PostgreSQL documents and chunks for the curated trusted corpus.

LEGACY (step 20): a one-off for the reconciliation at migration 0005; it refuses any other revision, so it does not run
on a current database. To load the corpus use ``load_corpus.py`` (README.md, "Quick start"), which reuses this module's
``plan``/``execute`` at the current head. Kept for the record of how the development database was reconciled.

Sources (no other metadata is invented):
- documents: ``data/structured/manifests/trusted_judgment_processing_manifest.json``
- chunks:    ``data/processed/judgment_chunks/*.json``

Document columns: doc_type ("judgment"), case_name, court_name, court_level,
decision_date (only where the manifest has one), year, source_url, file_path,
checksum, source_document_key (the curated document_id, e.g.
``indian_kanoon:<id>``). case_number and the outcome columns stay null: no
source exists for them.

Chunk columns: chunk_index, text, chroma_id (the curated chunk_id, identical
to the Chroma and BM25 IDs), token_count (estimated_token_count), page and
paragraph provenance (a missing page stays NULL; Chroma and BM25 encode it as
-1 with has_page_provenance=false), section_heading (heading_path joined with
" > ", as services/chunker.py does).

Rows are matched by source_document_key and chroma_id. Missing rows are
inserted. Existing rows must match the sources exactly; any difference is
reported and the run aborts without writing, so a second run makes zero
changes. Requires migration 0005 (source_document_key). Chroma and BM25 are
never touched.

Usage (rehearsal):
    REHEARSAL_DATABASE_URL=... .venv/bin/python backend/scripts/reconcile_backfill.py \\
        --database-url-env REHEARSAL_DATABASE_URL --dry-run
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import reconcile_inventory as inventory_lib  # noqa: E402
from backend.scripts.reconcile_common import alembic_version, connect, resolve_database  # noqa: E402

REQUIRED_REVISION = "0005_corpus_keys"
DOCUMENT_COLUMNS = (
    "doc_type", "case_name", "court_name", "court_level", "case_number", "decision_date", "year",
    "case_disposition", "conviction_status", "appeal_result", "source_url", "file_path", "checksum",
    "source_document_key",
)
CHUNK_COLUMNS = (
    "chunk_index", "text", "chroma_id", "token_count", "page_start", "page_end",
    "paragraph_start", "paragraph_end", "section_heading",
)


def document_row(source: dict[str, Any]) -> dict[str, Any]:
    court = source.get("court") or {}
    decision_date = source.get("decision_date")
    return {
        "doc_type": "judgment",
        "case_name": source["case_title"],
        "court_name": court.get("court_name"),
        "court_level": court.get("court_level"),
        "case_number": None,
        "decision_date": date.fromisoformat(decision_date) if decision_date else None,
        "year": source.get("decision_year"),
        "case_disposition": None,
        "conviction_status": None,
        "appeal_result": None,
        "source_url": source.get("source_url"),
        "file_path": source.get("raw_path"),
        "checksum": source["sha256"],
        "source_document_key": source["document_id"],
    }


def chunk_row(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_index": source["chunk_index"],
        "text": source["chunk_text"],
        "chroma_id": source["chunk_id"],
        "token_count": source["estimated_token_count"],
        "page_start": source.get("page_start"),
        "page_end": source.get("page_end"),
        "paragraph_start": source.get("paragraph_start"),
        "paragraph_end": source.get("paragraph_end"),
        "section_heading": " > ".join(source.get("heading_path") or []) or None,
    }


def differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    return [column for column, value in expected.items() if actual.get(column) != value]


def plan(cursor: Any, *, ignore_document_columns: tuple[str, ...] = ()) -> dict[str, Any]:
    """``ignore_document_columns``: existing values in these columns are not compared (load_corpus.py passes the
    outcome columns, which produce_analytics_data.py fills after the load). Inserted rows still get NULL there."""
    documents, chunks = inventory_lib.load_curated_corpus()
    chunks_by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks.values():
        chunks_by_document.setdefault(chunk["document_id"], []).append(chunk)

    cursor.execute(f"SELECT id, {', '.join(DOCUMENT_COLUMNS)} FROM documents")
    existing_documents = [dict(zip(("id",) + DOCUMENT_COLUMNS, row)) for row in cursor.fetchall()]
    by_key = {row["source_document_key"]: row for row in existing_documents if row["source_document_key"]}
    by_checksum = {row["checksum"]: row for row in existing_documents if row["checksum"]}
    cursor.execute(f"SELECT id, document_id, {', '.join(CHUNK_COLUMNS)} FROM chunks")
    existing_chunks = [dict(zip(("id", "document_id") + CHUNK_COLUMNS, row)) for row in cursor.fetchall()]
    chunks_by_pg_document: dict[int, dict[str, dict[str, Any]]] = {}
    for row in existing_chunks:
        chunks_by_pg_document.setdefault(row["document_id"], {})[row["chroma_id"]] = row

    insert_documents, unchanged_documents, conflicts = [], 0, []
    insert_chunks: list[tuple[str, dict[str, Any]]] = []
    unchanged_chunks = 0
    for key in sorted(documents):
        expected = document_row(documents[key])
        existing = by_key.get(key)
        if existing is None and expected["checksum"] in by_checksum:
            conflicts.append(f"document {key}: checksum already used by postgres document {by_checksum[expected['checksum']]['id']} without this key")
            continue
        expected_chunks = {c["chunk_id"]: chunk_row(c) for c in chunks_by_document.get(key, [])}
        if existing is None:
            insert_documents.append(expected)
            insert_chunks.extend((key, row) for _, row in sorted(expected_chunks.items()))
            continue
        changed = [column for column in differences(expected, existing) if column not in ignore_document_columns]
        if changed:
            conflicts.append(f"document {key} (postgres id {existing['id']}): differs in {changed}")
            continue
        unchanged_documents += 1
        present = chunks_by_pg_document.get(existing["id"], {})
        extra = sorted(set(present) - set(expected_chunks))
        if extra:
            conflicts.append(f"document {key}: postgres has chunks not in the curated files: {extra}")
        for chunk_id, row in sorted(expected_chunks.items()):
            if chunk_id not in present:
                insert_chunks.append((key, row))
            elif differences(row, present[chunk_id]):
                conflicts.append(f"chunk {chunk_id}: differs in {differences(row, present[chunk_id])}")
            else:
                unchanged_chunks += 1
    return {
        "insert_documents": insert_documents,
        "insert_chunks": insert_chunks,
        "unchanged_documents": unchanged_documents,
        "unchanged_chunks": unchanged_chunks,
        "conflicts": conflicts,
        "curated_documents": len(documents),
        "curated_chunks": len(chunks),
    }


def execute(cursor: Any, work: dict[str, Any]) -> None:
    document_ids: dict[str, int] = {}
    for row in work["insert_documents"]:
        cursor.execute(
            f"INSERT INTO documents ({', '.join(DOCUMENT_COLUMNS)}) VALUES ({', '.join(['%s'] * len(DOCUMENT_COLUMNS))}) RETURNING id",
            [row[column] for column in DOCUMENT_COLUMNS],
        )
        document_ids[row["source_document_key"]] = cursor.fetchone()[0]
    missing_keys = {key for key, _ in work["insert_chunks"]} - set(document_ids)
    if missing_keys:
        cursor.execute("SELECT source_document_key, id FROM documents WHERE source_document_key = ANY(%s)", (sorted(missing_keys),))
        document_ids.update(dict(cursor.fetchall()))
    for key, row in work["insert_chunks"]:
        cursor.execute(
            f"INSERT INTO chunks (document_id, {', '.join(CHUNK_COLUMNS)}) VALUES (%s, {', '.join(['%s'] * len(CHUNK_COLUMNS))})",
            [document_ids[key]] + [row[column] for column in CHUNK_COLUMNS],
        )
    cursor.execute("SELECT count(*) FROM documents WHERE source_document_key IS NOT NULL")
    corpus_documents = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.source_document_key IS NOT NULL")
    corpus_chunks = cursor.fetchone()[0]
    if (corpus_documents, corpus_chunks) != (work["curated_documents"], work["curated_chunks"]):
        raise RuntimeError(
            f"post-condition failed: {corpus_documents} documents / {corpus_chunks} chunks, "
            f"expected {work['curated_documents']} / {work['curated_chunks']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)

    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=not args.dry_run)
    connection = connect(url, readonly=args.dry_run)
    try:
        with connection.cursor() as cursor:
            revision = alembic_version(cursor)
            if revision != REQUIRED_REVISION:
                raise SystemExit(f"refused: database '{database}' is at revision {revision}; run alembic upgrade head ({REQUIRED_REVISION}) first")
            work = plan(cursor)
            verb = "WOULD INSERT" if args.dry_run else "INSERTING"
            print(f"target database: {database}")
            print(f"  curated corpus: {work['curated_documents']} documents, {work['curated_chunks']} chunks")
            keys = [row["source_document_key"] for row in work["insert_documents"]]
            print(f"  {verb} documents: {len(keys)}" + (f" keys={keys}" if keys else ""))
            print(f"  {verb} chunks: {len(work['insert_chunks'])}")
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
            execute(cursor, work)
        connection.commit()
        print(f"changes: {changes}")
        return 0
    finally:
        if not connection.closed:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
