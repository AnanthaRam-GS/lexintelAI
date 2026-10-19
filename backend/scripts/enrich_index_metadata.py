"""Add index_metadata_v1 fields to every Chroma and BM25 chunk, derived from PostgreSQL.

Fields (``backend/app/services/index_metadata.py``, ``docs/INDEX_METADATA.md``):
``doc_type``, ``cited_sections``, ``offence_sections``, ``chunk_sections``,
their counts and ``index_metadata_version``. ``effective_legal_regime`` is
filled from the cited statutes only where a chunk has no value (admin
uploads); existing values are never changed. ``effective_offence_family`` is
not derivable and is never written.

Only metadata changes. Chroma is updated with ``collection.update(ids,
metadatas)``, which merges keys and leaves embeddings and documents alone; an
empty list deletes its key. BM25 changes only ``records[].metadata``. Its
statistics (``doc_freqs``, ``avg_doc_length``, term frequencies, lengths and
the index ``metadata`` block with its fingerprint) are not recomputed and are
checked to be unchanged before the file is replaced.

Refuses to run unless PostgreSQL, Chroma and BM25 hold exactly the same chunk
IDs (run ``verify_store_consistency.py`` first). Dry runs read Chroma through
read-only SQLite and write nothing. Idempotent: a second run makes 0 changes.

Usage:
    .venv/bin/python backend/scripts/enrich_index_metadata.py --database-url-env DATABASE_URL \\
        --chroma-dir chroma_store --bm25-file bm25_store/legalai_trusted_judgments_bm25_v1.json [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.index_metadata import FIELDS, REGIME_FIELD, expected_from_postgres, store_form  # noqa: E402
from backend.scripts.reconcile_common import check_store_paths, connect, resolve_database  # noqa: E402
from backend.scripts.verify_store_consistency import read_chroma  # noqa: E402

UPDATE_BATCH = 500
BM25_STATISTICS = ("metadata", "doc_freqs", "avg_doc_length")


def planned_updates(expected: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], Counter]:
    """{chunk_id: {key: new value or None (delete)}} for the keys that differ, and changes per key."""
    updates: dict[str, dict[str, Any]] = {}
    changed: Counter = Counter()
    for chunk_id, entry in expected.items():
        metadata = current[chunk_id]
        wanted = store_form(entry["fields"])
        if metadata.get(REGIME_FIELD) is None:
            wanted[REGIME_FIELD] = entry["derived_regime"]
        delta = {key: value for key, value in wanted.items() if metadata.get(key) != value}
        if delta:
            updates[chunk_id] = delta
            changed.update(delta.keys())
    return updates, changed


def bm25_statistics_digest(payload: dict[str, Any]) -> str:
    """Hash of everything in the BM25 file except records[].metadata."""
    statistics = {key: payload[key] for key in BM25_STATISTICS}
    statistics["records"] = [{k: v for k, v in record.items() if k != "metadata"} for record in payload["records"]]
    return hashlib.sha256(json.dumps(statistics, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def apply_bm25(path: Path, updates: dict[str, dict[str, Any]]) -> None:
    from backend.app.services.retrieval.bm25 import Bm25LexicalIndex

    index_name = path.name.removesuffix(".json")
    before = bm25_statistics_digest(json.loads(path.read_text(encoding="utf-8")))
    index = Bm25LexicalIndex(path.parent, index_name)
    for chunk_id, delta in updates.items():
        metadata = index.records[chunk_id]["metadata"]
        for key, value in delta.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = value
    payload = {"metadata": index.metadata, "doc_freqs": index.doc_freqs, "avg_doc_length": index.avg_doc_length,
               "records": list(index.records.values())}
    if bm25_statistics_digest(payload) != before:
        raise SystemExit("refused: BM25 statistics would change; nothing was written to BM25")
    index.persist()


def apply_chroma(chroma_dir: Path, collection: str, updates: dict[str, dict[str, Any]]) -> None:
    import chromadb

    if not (chroma_dir / "chroma.sqlite3").is_file():
        raise SystemExit(f"refused: no Chroma store at {chroma_dir}")
    target = chromadb.PersistentClient(path=str(chroma_dir)).get_collection(collection)
    items = sorted(updates.items())
    for start in range(0, len(items), UPDATE_BATCH):
        batch = items[start:start + UPDATE_BATCH]
        target.update(ids=[chunk_id for chunk_id, _ in batch], metadatas=[delta for _, delta in batch])


def main(argv: list[str] | None = None) -> int:
    from backend.app.core.config import Settings, resolve_chroma_location
    from backend.scripts.verify_store_consistency import read_bm25

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the database URL.")
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--bm25-file", type=Path, required=True)
    parser.add_argument("--collection", help="Chroma collection (default: the configured CHROMA_COLLECTION_NAME).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)
    write = not args.dry_run
    collection = args.collection or resolve_chroma_location(Settings())[1]

    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=write)
    check_store_paths([args.chroma_dir, args.bm25_file], confirm_dev=args.confirm_dev, write=write)

    connection = connect(url, readonly=True)
    try:
        with connection.cursor() as cursor:
            expected = expected_from_postgres(cursor)
    finally:
        connection.rollback()
        connection.close()
    chroma, collections = read_chroma(args.chroma_dir, collection)
    if collection not in collections:
        raise SystemExit(f"refused: Chroma collection '{collection}' does not exist")
    bm25, _, _ = read_bm25(args.bm25_file)
    for name, index in (("chroma", chroma), ("bm25", bm25)):
        if set(index) != set(expected):
            raise SystemExit(
                f"refused: {name} and PostgreSQL chunk IDs differ ({len(set(expected) - set(index))} missing, "
                f"{len(set(index) - set(expected))} extra); run verify_store_consistency.py"
            )

    chroma_updates, chroma_changed = planned_updates(expected, chroma)
    bm25_updates, bm25_changed = planned_updates(expected, bm25)
    print(f"index metadata enrichment database={database} collection={collection}" + (" (dry-run)" if args.dry_run else ""))
    print(f"  chunks: {len(expected)}")
    for name, updates, changed in (("chroma", chroma_updates, chroma_changed), ("bm25", bm25_updates, bm25_changed)):
        print(f"  {name}: chunks to update {len(updates)}; keys changed {dict(sorted(changed.items()))}")
    if write:
        if chroma_updates:
            apply_chroma(args.chroma_dir, collection, chroma_updates)
        if bm25_updates:
            apply_bm25(args.bm25_file, bm25_updates)
    total = len(chroma_updates) + len(bm25_updates)
    print(f"{'dry run: ' if args.dry_run else ''}chunk updates{' that would be made' if args.dry_run else ''}: {total}")
    print(f"  fields: {', '.join(FIELDS)}; {REGIME_FIELD} only where absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
