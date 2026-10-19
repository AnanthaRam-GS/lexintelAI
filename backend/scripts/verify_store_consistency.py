"""Read-only check that PostgreSQL matches the Chroma collection and BM25.

PostgreSQL is canonical. For every PostgreSQL chunk, the Chroma collection and
the BM25 index must hold an entry with the same ID (``chunks.chroma_id``),
the same document (``documents.source_document_key``, or the PostgreSQL
document id for admin-ingested ``doc:<id>`` chunks), the same text hash, and
the same chunk index and page/paragraph provenance. A missing page is NULL in
PostgreSQL and ``-1`` with ``has_page_provenance=false`` in the indexes. The
indexes must hold nothing else, and the Chroma database must hold no other
collection unless ``--allow-extra-collections`` is given. BM25's stored
metadata (chunk count, document count, fingerprint) must match its records.

Index metadata (``index_metadata_v1``, see ``services/index_metadata.py``):
each chunk's ``doc_type``, ``cited_sections``, ``offence_sections``,
``chunk_sections``, their counts and ``index_metadata_version`` must equal
what PostgreSQL derives, in both indexes. ``effective_legal_regime`` must be
present and in the regime vocabulary; for admin uploads (``admin:`` keys) it
must equal the regime derived from the cited statutes. Curated-corpus values
come from the reviewed acquisition manifest, which PostgreSQL does not hold,
so only their vocabulary and their consistency within a document are checked.
``effective_offence_family``, where present, must be the same on every chunk
of a document.

Nothing is modified: PostgreSQL is read in a read-only session, Chroma through
SQLite ``mode=ro&immutable=1``, and BM25 as JSON. Exits 0 when consistent and
1 on any mismatch.

Usage:
    .venv/bin/python backend/scripts/verify_store_consistency.py --database-url-env DATABASE_URL \\
        --chroma-dir chroma_store --bm25-file bm25_store/legalai_trusted_judgments_bm25_v1.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.index_metadata import FIELDS, REGIME_FIELD, expected_from_postgres, index_view  # noqa: E402
from backend.app.services.legal_regime import REGIMES  # noqa: E402
from backend.scripts.reconcile_common import connect, resolve_database  # noqa: E402

PROVENANCE = ("chunk_index", "page_start", "page_end", "paragraph_start", "paragraph_end")
NULL_PAGE_FIELDS = ("page_start", "page_end")
SHOW_IDS = 20


def text_hash(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_int(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


def read_postgres(url: str) -> dict[str, dict[str, Any]]:
    connection = connect(url, readonly=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise SystemExit("PostgreSQL session is not read-only; aborting.")
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'documents' AND column_name = 'source_document_key'"
            )
            has_key = cursor.fetchone()[0] == 1  # absent before migration 0005
            cursor.execute(f"SELECT id, {'source_document_key' if has_key else 'NULL'} FROM documents")
            documents = {row[0]: row[1] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT id, document_id, chroma_id, text, chunk_index, page_start, page_end, paragraph_start, paragraph_end FROM chunks"
            )
            rows = cursor.fetchall()
            index_expected = expected_from_postgres(cursor)
    finally:
        connection.rollback()
        connection.close()
    chunks: dict[str, dict[str, Any]] = {}
    problems: dict[str, list[str]] = defaultdict(list)
    for chunk_pk, document_id, chroma_id, text, *provenance in rows:
        if not chroma_id:
            problems["postgres_chunks_without_chroma_id"].append(str(chunk_pk))
            continue
        if chroma_id in chunks:
            problems["postgres_duplicate_chroma_id"].append(chroma_id)
        key = documents.get(document_id)
        chunks[chroma_id] = {
            "document": key if key else str(document_id),
            "text_hash": text_hash(text),
            **dict(zip(PROVENANCE, provenance)),
        }
    documents_with_chunks = {entry["document"] for entry in chunks.values()}
    for document_id, key in documents.items():
        if (key or str(document_id)) not in documents_with_chunks:
            problems["postgres_documents_without_chunks"].append(key or str(document_id))
    return {"chunks": chunks, "problems": problems, "index_expected": index_expected}


def read_chroma(chroma_dir: Path, collection: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    connection = sqlite3.connect(f"file:{chroma_dir / 'chroma.sqlite3'}?mode=ro&immutable=1", uri=True)
    try:
        collections = [row[0] for row in connection.execute("SELECT name FROM collections ORDER BY name")]
        if collection not in collections:
            return {}, collections
        rows = connection.execute(
            """
            SELECT e.embedding_id, m.key, m.string_value, m.int_value, m.float_value, m.bool_value
            FROM embeddings e
            JOIN segments s ON s.id = e.segment_id
            JOIN collections c ON c.id = s.collection
            LEFT JOIN embedding_metadata m ON m.id = e.id
            WHERE c.name = ?
            """,
            (collection,),
        )
        entries: dict[str, dict[str, Any]] = {}
        for embedding_id, key, *values in rows:
            metadata = entries.setdefault(embedding_id, {})
            if key is not None:
                metadata[key] = next((v for v in values if v is not None), None)
        # List metadata (Chroma >= 1.5) is stored one element per row.
        arrays = connection.execute(
            """
            SELECT e.embedding_id, a.key, a.string_value, a.int_value, a.float_value, a.bool_value
            FROM embedding_metadata_array a
            JOIN embeddings e ON e.id = a.id
            JOIN segments s ON s.id = e.segment_id
            JOIN collections c ON c.id = s.collection
            WHERE c.name = ?
            ORDER BY a.rowid
            """,
            (collection,),
        ) if _has_table(connection, "embedding_metadata_array") else []
        for embedding_id, key, *values in arrays:
            entries.setdefault(embedding_id, {}).setdefault(key, []).append(next((v for v in values if v is not None), None))
    finally:
        connection.close()
    return (
        {
            entry_id: {**metadata, "text": metadata.get("chroma:document")}
            for entry_id, metadata in entries.items()
        },
        collections,
    )


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def compare_index_metadata(
    name: str, expected: dict[str, dict[str, Any]], index: dict[str, dict[str, Any]], problems: dict[str, list[str]]
) -> None:
    """index_metadata_v1 fields and the effective_* fields of every chunk present in both."""
    regimes: dict[str, set] = defaultdict(set)
    families: dict[str, set] = defaultdict(set)
    for chunk_id in sorted(set(expected) & set(index)):
        entry, metadata = expected[chunk_id], index[chunk_id]
        view = index_view(metadata)
        for field in FIELDS:
            if view[field] != entry["fields"][field]:
                problems[f"{name}_{field}_mismatch"].append(chunk_id)
        regime = metadata.get(REGIME_FIELD)
        if regime not in REGIMES:
            problems[f"{name}_{REGIME_FIELD}_missing_or_invalid"].append(chunk_id)
        elif entry["document_key"].startswith("admin:") and regime != entry["derived_regime"]:
            problems[f"{name}_{REGIME_FIELD}_mismatch"].append(chunk_id)
        regimes[entry["document_key"]].add(regime)
        families[entry["document_key"]].add(metadata.get("effective_offence_family"))
    for key in sorted(regimes):
        if len(regimes[key]) > 1:
            problems[f"{name}_{REGIME_FIELD}_differs_within_document"].append(key)
        if len(families[key]) > 1:
            problems[f"{name}_effective_offence_family_differs_within_document"].append(key)


def read_bm25(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = {
        record["chunk_id"]: {**(record.get("metadata") or {}), "document_id": record.get("document_id"), "text": record.get("text")}
        for record in data["records"]
    }
    return entries, data["metadata"], data["records"]


def compare_index(name: str, pg_chunks: dict[str, dict[str, Any]], index: dict[str, dict[str, Any]], problems: dict[str, list[str]]) -> None:
    for chunk_id in sorted(set(pg_chunks) - set(index)):
        problems[f"{name}_missing_postgres_chunk"].append(chunk_id)
    for chunk_id in sorted(set(index) - set(pg_chunks)):
        problems[f"{name}_entry_not_in_postgres"].append(chunk_id)
    for chunk_id in sorted(set(pg_chunks) & set(index)):
        expected, entry = pg_chunks[chunk_id], index[chunk_id]
        if str(entry.get("document_id")) != expected["document"]:
            problems[f"{name}_document_mismatch"].append(chunk_id)
        if text_hash(entry.get("text")) != expected["text_hash"]:
            problems[f"{name}_text_hash_mismatch"].append(chunk_id)
        for field in PROVENANCE:
            value = as_int(entry.get(field))
            if field in NULL_PAGE_FIELDS and expected[field] is None:
                if value != -1 or entry.get("has_page_provenance"):
                    problems[f"{name}_{field}_mismatch"].append(chunk_id)
            elif value != expected[field]:
                problems[f"{name}_{field}_mismatch"].append(chunk_id)


def check_bm25_metadata(metadata: dict[str, Any], records: list[dict[str, Any]], problems: dict[str, list[str]]) -> str | None:
    from backend.app.services.retrieval.bm25 import chunk_universe_fingerprint

    chunks = [
        {
            "chunk_id": record["chunk_id"],
            "document_id": record["document_id"],
            "chunk_text": record["text"],
            "normalizer_version": (record.get("metadata") or {}).get("normalizer_version"),
            "chunker_version": (record.get("metadata") or {}).get("chunker_version"),
        }
        for record in records
    ]
    fingerprint = chunk_universe_fingerprint(chunks)
    if metadata.get("chunk_universe_fingerprint") != fingerprint:
        problems["bm25_fingerprint_does_not_match_records"].append(str(metadata.get("chunk_universe_fingerprint")))
    if metadata.get("chunk_count") != len(records):
        problems["bm25_chunk_count_does_not_match_records"].append(f"{metadata.get('chunk_count')} != {len(records)}")
    if metadata.get("document_count") != len({record["document_id"] for record in records}):
        problems["bm25_document_count_does_not_match_records"].append(str(metadata.get("document_count")))
    return fingerprint


def main(argv: list[str] | None = None) -> int:
    from backend.app.core.config import Settings, resolve_chroma_location

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", default="DATABASE_URL", help="Name of the env var holding the database URL.")
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--bm25-file", type=Path, required=True)
    parser.add_argument("--collection", help="Chroma collection (default: the configured CHROMA_COLLECTION_NAME).")
    parser.add_argument("--allow-extra-collections", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args(argv)
    collection = args.collection or resolve_chroma_location(Settings())[1]

    url, database = resolve_database(args.database_url_env, confirm_dev=False, write=False)
    pg = read_postgres(url)
    problems = pg["problems"]
    chroma, collections = read_chroma(args.chroma_dir, collection)
    if collection not in collections:
        problems["chroma_collection_missing"].append(collection)
    extra = [name for name in collections if name != collection]
    if extra and not args.allow_extra_collections:
        problems["chroma_extra_collections"].extend(extra)
    bm25, bm25_metadata, bm25_records = read_bm25(args.bm25_file)
    fingerprint = check_bm25_metadata(bm25_metadata, bm25_records, problems)
    compare_index("chroma", pg["chunks"], chroma, problems)
    compare_index("bm25", pg["chunks"], bm25, problems)
    compare_index_metadata("chroma", pg["index_expected"], chroma, problems)
    compare_index_metadata("bm25", pg["index_expected"], bm25, problems)

    pg_documents = {entry["document"] for entry in pg["chunks"].values()}
    summary = {
        "database": database,
        "collection": collection,
        "postgres": {"chunks": len(pg["chunks"]), "documents_with_chunks": len(pg_documents)},
        "chroma": {"entries": len(chroma), "documents": len({str(e.get("document_id")) for e in chroma.values()}), "collections": collections},
        "bm25": {"records": len(bm25), "documents": len({str(e.get("document_id")) for e in bm25.values()}), "fingerprint": fingerprint},
        "mismatches": {key: len(values) for key, values in sorted(problems.items()) if values},
        "mismatch_ids": {key: sorted(values) for key, values in sorted(problems.items()) if values},
        "consistent": not any(problems.values()),
    }
    print(f"database={database} collection={collection}")
    print(f"  postgres: {summary['postgres']['chunks']} chunks across {summary['postgres']['documents_with_chunks']} documents")
    print(f"  chroma:   {summary['chroma']['entries']} entries across {summary['chroma']['documents']} documents; collections={collections}")
    print(f"  bm25:     {summary['bm25']['records']} records across {summary['bm25']['documents']} documents; fingerprint={fingerprint}")
    for key, values in summary["mismatch_ids"].items():
        shown = ", ".join(values[:SHOW_IDS]) + (f", ... (+{len(values) - SHOW_IDS})" if len(values) > SHOW_IDS else "")
        print(f"  MISMATCH {key}: {len(values)} [{shown}]")
    print("CONSISTENT" if summary["consistent"] else "INCONSISTENT")
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if summary["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
