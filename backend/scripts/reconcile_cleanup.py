"""Remove the test pollution identified by the reconciliation inventory.

Targets are recomputed from the target database and stores with the same
classification as ``reconcile_inventory.py``, and every target must also be
classified ``test_pollution`` in the committed inventory (``--inventory``).
Anything else is refused, so this script can only remove what the inventory
reported.

What it removes:
- PostgreSQL: test-pollution documents (their chunks and document sections
  go with them through ON DELETE CASCADE), ingestion jobs belonging to those
  documents or to no document and no stored upload, test-fixture users (their
  OTPs, tokens and lawyer applications cascade), and, with
  ``--delete-seed-account-history``, query history owned by seed accounts.
  Seed accounts, unclassified users and ``--keep-user-id`` users are kept.
- BM25: records classified test_pollution; statistics and index metadata are
  recomputed.
- Chroma: collections other than ``--keep-collection`` whose every entry is
  test_pollution in the inventory, plus their HNSW segment directories
  (``delete_collection`` leaves them on disk) and any segment directory no
  segment references.
- With ``--archive-json-mirrors DIR``: JsonVectorStore mock-embedding files in
  the Chroma directory are moved to DIR. No code path reads them (only
  ``build_vector_index.py --store json`` writes them).

The FK ON DELETE rules are checked against the database catalog first.
PostgreSQL deletions run in one transaction with post-condition checks.
Every step is idempotent: a second run reports zero changes.

Usage (rehearsal):
    REHEARSAL_DATABASE_URL=... .venv/bin/python backend/scripts/reconcile_cleanup.py \\
        --database-url-env REHEARSAL_DATABASE_URL --chroma-dir /tmp/x/chroma_store \\
        --bm25-file /tmp/x/bm25_store/legalai_trusted_judgments_bm25_v1.json \\
        --archive-json-mirrors /tmp/x/mirror_archive --delete-seed-account-history \\
        --keep-user-id 123 --dry-run
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import DEFAULT_CHROMA_COLLECTION  # noqa: E402
from backend.scripts import reconcile_inventory as inventory_lib  # noqa: E402
from backend.scripts.reconcile_common import (  # noqa: E402
    REPO_ROOT,
    check_store_paths,
    connect,
    resolve_database,
    verify_fk_rules,
)

DEFAULT_INVENTORY = REPO_ROOT / "docs/reconciliation/inventory.json"
UUID_DIR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HNSW_FILES = {"data_level0.bin", "header.bin", "length.bin", "link_lists.bin", "index_metadata.pickle"}
DEFAULT_UPLOADS_DIR = REPO_ROOT / "data/raw/uploads"
BM25_STORE_KEY = "bm25:legalai_trusted_judgments_bm25_v1"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--bm25-file", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--uploads-dir", type=Path, default=DEFAULT_UPLOADS_DIR, help="Read-only: jobs with a stored upload are kept.")
    parser.add_argument("--keep-collection", default=DEFAULT_CHROMA_COLLECTION)
    parser.add_argument("--keep-user-id", type=int, action="append", default=[])
    parser.add_argument("--delete-seed-account-history", action="store_true")
    parser.add_argument("--archive-json-mirrors", type=Path, help="Move mock JsonVectorStore files here.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    return parser.parse_args(argv)


def load_allowed(inventory_path: Path) -> dict[str, Any]:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    classification = data["classification"]
    tables = data["non_document_tables"]
    jobs = tables["ingestion_jobs_by_status_and_document_category"]
    return {
        "documents": set(classification["postgres:documents"]["test_pollution"]),
        "bm25": set(classification[BM25_STORE_KEY]["test_pollution"]),
        "chroma": {
            key.removeprefix("chroma:"): set(value["test_pollution"])
            for key, value in classification.items()
            if key.startswith("chroma:")
        },
        "chroma_totals": {
            key.removeprefix("chroma:"): summary["total"] for key, summary in data["stores"].items() if key.startswith("chroma:")
        },
        "mirrors": {
            key.removeprefix("json_mirror:chroma_store/"): summary
            for key, summary in data["auxiliary_stores"].items()
            if key.startswith("json_mirror:")
        },
        "max_test_users": tables["users_by_category"].get("test_fixture", 0),
        "max_jobs": sum(n for key, n in jobs.items() if key.split("|")[1] in {"test_pollution", "no_document"}),
        "max_seed_history": tables["query_history_by_user_category"].get("seed_account", 0),
    }


def read_postgres_state(cursor: Any) -> dict[str, list[tuple]]:
    queries = {
        "documents": (
            "SELECT id, doc_type, case_name, court_name, court_level, case_number, decision_date, year, case_disposition, "
            "conviction_status, appeal_result, source_url, file_path, checksum FROM documents ORDER BY id"
        ),
        "chunks": "SELECT id, document_id FROM chunks ORDER BY id",
        "users": "SELECT id, lower(email) FROM users ORDER BY id",
        "query_history": "SELECT id, user_id FROM query_history ORDER BY id",
        "ingestion_jobs": "SELECT id, document_id FROM ingestion_jobs ORDER BY id",
        "lawyer_verification_applications": "SELECT id, user_id FROM lawyer_verification_applications ORDER BY id",
        "email_verification_otps": "SELECT id, user_id FROM email_verification_otps ORDER BY id",
        "email_verification_tokens": "SELECT id, user_id FROM email_verification_tokens ORDER BY id",
        "document_sections": "SELECT id, document_id FROM document_sections ORDER BY id",
    }
    state = {}
    for name, sql in queries.items():
        cursor.execute(sql)
        state[name] = cursor.fetchall()
    return state


def plan_postgres(state: dict[str, list[tuple]], allowed: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    curated_documents, _ = inventory_lib.load_curated_corpus()
    corpus_shas = {d["sha256"] for d in curated_documents.values()}
    corpus_urls = {d["source_url"] for d in curated_documents.values()}
    literals = inventory_lib.test_literals()
    seeds = inventory_lib.seed_emails()
    test_domains = inventory_lib.test_email_domains(literals)
    columns = (
        "id", "doc_type", "case_name", "court_name", "court_level", "case_number", "decision_date", "year",
        "case_disposition", "conviction_status", "appeal_result", "source_url", "file_path", "checksum",
    )
    document_categories = {
        row[0]: inventory_lib.classify_pg_document(dict(zip(columns, row)), corpus_shas, corpus_urls, literals)[0]
        for row in state["documents"]
    }
    documents = sorted(i for i, c in document_categories.items() if c == "test_pollution")
    refused = sorted(set(documents) - allowed["documents"])
    if refused:
        raise SystemExit(f"refused: documents {refused} are test_pollution here but not in the inventory")

    user_categories = {user_id: inventory_lib.classify_user(email, seeds, test_domains) for user_id, email in state["users"]}
    users = sorted(i for i, c in user_categories.items() if c == "test_fixture" and i not in args.keep_user_id)
    for keep in args.keep_user_id:
        if keep not in user_categories:
            raise SystemExit(f"refused: --keep-user-id {keep} does not exist in the target database")
    if len(users) > allowed["max_test_users"]:
        raise SystemExit(f"refused: {len(users)} test-fixture users exceed the inventory's {allowed['max_test_users']}")

    stored_uploads = {path.name.split("_", 1)[0] for path in args.uploads_dir.glob("*_*")} if args.uploads_dir.exists() else set()
    target_documents = set(documents)
    jobs = sorted(
        job_id
        for job_id, document_id in state["ingestion_jobs"]
        if document_id in target_documents or (document_id is None and job_id not in stored_uploads)
    )
    if len(jobs) > allowed["max_jobs"]:
        raise SystemExit(f"refused: {len(jobs)} ingestion jobs exceed the inventory's {allowed['max_jobs']}")

    seed_ids = {i for i, c in user_categories.items() if c == "seed_account"}
    history = sorted(h for h, user_id in state["query_history"] if user_id in seed_ids) if args.delete_seed_account_history else []
    if len(history) > allowed["max_seed_history"]:
        raise SystemExit(f"refused: {len(history)} seed-account history rows exceed the inventory's {allowed['max_seed_history']}")
    deleted_users = set(users)
    orphaned_history = [h for h, user_id in state["query_history"] if user_id in deleted_users]
    if orphaned_history:
        raise SystemExit(f"refused: history rows {orphaned_history} belong to users being deleted; decide on them first")

    def owned(table: str, key_index: int, owners: set) -> list:
        return sorted(row[0] for row in state[table] if row[key_index] in owners)

    return {
        "documents": documents,
        "cascade_chunks": owned("chunks", 1, target_documents),
        "cascade_document_sections": owned("document_sections", 1, target_documents),
        "ingestion_jobs": jobs,
        "users": users,
        "cascade_lawyer_verification_applications": owned("lawyer_verification_applications", 1, deleted_users),
        "cascade_email_verification_otps": owned("email_verification_otps", 1, deleted_users),
        "cascade_email_verification_tokens": owned("email_verification_tokens", 1, deleted_users),
        "query_history": history,
        "kept_users_by_category": dict(
            sorted(Counter(c for i, c in user_categories.items() if i not in deleted_users).items())
        ),
        "kept_user_ids": sorted(set(user_categories) - deleted_users),
    }


def plan_stores(args: argparse.Namespace, allowed: dict[str, Any]) -> dict[str, Any]:
    _, bm25_records = inventory_lib.read_bm25(args.bm25_file)
    bm25_targets = sorted(set(bm25_records) & allowed["bm25"])

    chroma = inventory_lib.read_chroma(args.chroma_dir)["collections"]
    collections = []
    for name, collection in sorted(chroma.items()):
        if name == args.keep_collection:
            continue
        ids = set(collection["embeddings"])
        allowed_ids = allowed["chroma"].get(name, set())
        if not ids <= allowed_ids or not allowed_ids:
            raise SystemExit(f"refused: Chroma collection '{name}' has entries that are not test_pollution in the inventory")
        collections.append({"name": name, "entries": sorted(ids)})
    if args.keep_collection not in chroma:
        raise SystemExit(f"refused: keep collection '{args.keep_collection}' is missing from {args.chroma_dir}")

    # Chroma's delete_collection leaves the HNSW segment directory on disk.
    # Remove the directories of collections deleted here and any directory no
    # segment references (dead files Chroma never reads).
    referenced = chroma_segment_ids(args.chroma_dir)
    deleted_names = {collection["name"] for collection in collections}
    segment_dirs = sorted(
        path.name
        for path in args.chroma_dir.iterdir()
        if path.is_dir()
        and UUID_DIR.match(path.name)
        and {child.name for child in path.iterdir()} <= HNSW_FILES
        and (path.name not in referenced or referenced[path.name] in deleted_names)
    )

    mirrors = []
    if args.archive_json_mirrors:
        for file_name, mirror in inventory_lib.read_json_vector_mirrors(args.chroma_dir).items():
            expected = allowed["mirrors"].get(file_name)
            if expected is None:
                raise SystemExit(f"refused: {file_name} is not a JSON mirror listed in the inventory")
            if mirror["metadata"].get("build_mode") != "mock_validation_only":
                raise SystemExit(f"refused: {file_name} is not a mock-validation build")
            mirrors.append({"file": file_name, "records": len(mirror["records"])})
    return {
        "bm25_records": bm25_targets,
        "chroma_collections": collections,
        "chroma_segment_dirs": segment_dirs,
        "json_mirrors": mirrors,
    }


def chroma_segment_ids(chroma_dir: Path) -> dict[str, str]:
    """{segment id: collection name} for every segment in the Chroma database (read-only)."""
    import sqlite3

    connection = sqlite3.connect(f"file:{chroma_dir / 'chroma.sqlite3'}?mode=ro&immutable=1", uri=True)
    try:
        return {
            segment_id: name
            for segment_id, name in connection.execute(
                "SELECT s.id, c.name FROM segments s JOIN collections c ON c.id = s.collection"
            )
        }
    finally:
        connection.close()


def print_plan(database: str, pg_plan: dict[str, Any], store_plan: dict[str, Any], dry_run: bool) -> int:
    verb = "WOULD DELETE" if dry_run else "DELETING"
    print(f"target database: {database}")
    total = 0
    for key in (
        "documents", "cascade_chunks", "cascade_document_sections", "ingestion_jobs", "users",
        "cascade_lawyer_verification_applications", "cascade_email_verification_otps",
        "cascade_email_verification_tokens", "query_history",
    ):
        ids = pg_plan[key]
        total += len(ids)
        print(f"  {verb} postgres {key}: {len(ids)}" + (f" ids={ids}" if ids else ""))
    print(f"  keeping users: {pg_plan['kept_users_by_category']} ids={pg_plan['kept_user_ids']}")
    print(f"  {verb} bm25 records: {len(store_plan['bm25_records'])}" + (f" ids={store_plan['bm25_records']}" if store_plan["bm25_records"] else ""))
    for collection in store_plan["chroma_collections"]:
        print(f"  {verb} chroma collection '{collection['name']}' ({len(collection['entries'])} entries: {collection['entries']})")
    if not store_plan["chroma_collections"]:
        print(f"  {verb} chroma collections: 0")
    print(
        f"  {verb} chroma segment directories: {len(store_plan['chroma_segment_dirs'])}"
        + (f" {store_plan['chroma_segment_dirs']}" if store_plan["chroma_segment_dirs"] else "")
    )
    for mirror in store_plan["json_mirrors"]:
        print(f"  {'WOULD ARCHIVE' if dry_run else 'ARCHIVING'} json mirror {mirror['file']} ({mirror['records']} records)")
    if not store_plan["json_mirrors"]:
        print(f"  {'WOULD ARCHIVE' if dry_run else 'ARCHIVING'} json mirrors: 0")
    total += (
        len(store_plan["bm25_records"])
        + len(store_plan["chroma_collections"])
        + len(store_plan["chroma_segment_dirs"])
        + len(store_plan["json_mirrors"])
    )
    return total


def execute_postgres(connection: Any, pg_plan: dict[str, Any], before: dict[str, list[tuple]]) -> None:
    with connection.cursor() as cursor:
        for table, key in (
            ("query_history", "query_history"),
            ("ingestion_jobs", "ingestion_jobs"),
            ("documents", "documents"),
            ("users", "users"),
        ):
            ids = pg_plan[key]
            if not ids:
                continue
            cursor.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", (list(ids),))
            if cursor.rowcount != len(ids):
                raise RuntimeError(f"{table}: expected to delete {len(ids)} rows, deleted {cursor.rowcount}")
        after = read_postgres_state(cursor)
        expected_remaining = {
            "documents": len(before["documents"]) - len(pg_plan["documents"]),
            "chunks": len(before["chunks"]) - len(pg_plan["cascade_chunks"]),
            "document_sections": len(before["document_sections"]) - len(pg_plan["cascade_document_sections"]),
            "ingestion_jobs": len(before["ingestion_jobs"]) - len(pg_plan["ingestion_jobs"]),
            "users": len(before["users"]) - len(pg_plan["users"]),
            "lawyer_verification_applications": len(before["lawyer_verification_applications"]) - len(pg_plan["cascade_lawyer_verification_applications"]),
            "email_verification_otps": len(before["email_verification_otps"]) - len(pg_plan["cascade_email_verification_otps"]),
            "email_verification_tokens": len(before["email_verification_tokens"]) - len(pg_plan["cascade_email_verification_tokens"]),
            "query_history": len(before["query_history"]) - len(pg_plan["query_history"]),
        }
        actual_remaining = {table: len(after[table]) for table in expected_remaining}
        if actual_remaining != expected_remaining:
            raise RuntimeError(f"post-condition failed: expected {expected_remaining}, found {actual_remaining}")
        kept = {row[0] for row in after["users"]}
        if not set(pg_plan["kept_user_ids"]) <= kept:
            raise RuntimeError("post-condition failed: a kept user was removed")
    connection.commit()


def execute_stores(args: argparse.Namespace, store_plan: dict[str, Any]) -> None:
    if store_plan["bm25_records"]:
        from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_B, DEFAULT_K1

        index = Bm25LexicalIndex(args.bm25_file.parent, args.bm25_file.stem, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
        for chunk_id in store_plan["bm25_records"]:
            del index.records[chunk_id]
        index.recompute_statistics()
        index.metadata = index.index_metadata_from_records(empty_tokenized_docs=int(index.metadata.get("empty_tokenized_docs", 0)))
        index.persist()
        print(f"  bm25: {index.count()} records, fingerprint {index.metadata['chunk_universe_fingerprint']}")

    if store_plan["chroma_collections"]:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(path=str(args.chroma_dir), settings=ChromaSettings(anonymized_telemetry=False))
        for collection in store_plan["chroma_collections"]:
            client.delete_collection(collection["name"])
        print(f"  chroma collections now: {sorted(c.name for c in client.list_collections())}")

    for directory in store_plan["chroma_segment_dirs"]:
        path = args.chroma_dir / directory
        if path.exists():
            shutil.rmtree(path)

    if store_plan["json_mirrors"]:
        args.archive_json_mirrors.mkdir(parents=True, exist_ok=True)
        for mirror in store_plan["json_mirrors"]:
            destination = args.archive_json_mirrors / mirror["file"]
            if destination.exists():
                raise RuntimeError(f"archive destination {destination} already exists")
            shutil.move(str(args.chroma_dir / mirror["file"]), str(destination))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write = not args.dry_run
    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=write)
    check_store_paths([args.chroma_dir, args.bm25_file], confirm_dev=args.confirm_dev, write=write)
    if args.archive_json_mirrors:
        archive = args.archive_json_mirrors.resolve()
        if archive == REPO_ROOT or REPO_ROOT in archive.parents:
            raise SystemExit("refused: --archive-json-mirrors must be outside the repository")
    allowed = load_allowed(args.inventory)

    connection = connect(url, readonly=args.dry_run)
    try:
        with connection.cursor() as cursor:
            verify_fk_rules(cursor)
            before = read_postgres_state(cursor)
        pg_plan = plan_postgres(before, allowed, args)
        store_plan = plan_stores(args, allowed)
        changes = print_plan(database, pg_plan, store_plan, args.dry_run)
        if args.dry_run:
            connection.rollback()
            print(f"dry run: {changes} changes would be made")
            return 0
        execute_postgres(connection, pg_plan, before)
        execute_stores(args, store_plan)
        print(f"changes: {changes}")
        return 0
    finally:
        if not connection.closed:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
