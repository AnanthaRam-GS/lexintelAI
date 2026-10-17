"""Read-only reconciliation inventory across PostgreSQL, Chroma and BM25.

PostgreSQL is the canonical store; Chroma and BM25 are derived indexes. This
script compares all three with the curated trusted-judgment corpus and
classifies every PostgreSQL document and chunk, every Chroma embedding (in
every collection), and every BM25 record as exactly one of:

- ``corpus``: belongs to the curated trusted-judgment set
  (``trusted_judgment_processing_manifest.json`` plus its chunk files);
- ``admin_ingested``: uploaded through ``/ingest/upload``
  (``data/raw/uploads/``) and not a test fixture;
- ``test_pollution``: written by a test run (fixture values that appear as
  literals in ``backend/scripts/tests``), including index entries that point
  at such PostgreSQL documents;
- ``orphan``: present in one store with no source and no counterpart.

Nothing is modified:
- PostgreSQL is read in a read-only session (``SET SESSION CHARACTERISTICS AS
  TRANSACTION READ ONLY``) and the transaction is rolled back;
- Chroma's ``chroma.sqlite3`` is opened through SQLite with ``mode=ro`` and
  ``immutable=1``, so SQLite neither writes nor takes locks;
- BM25, chunk files and manifests are read as JSON.

Outputs contain IDs, hashes and counts only: no judgment text, case titles,
party names or user emails.

Usage:
    .venv/bin/python backend/scripts/reconcile_inventory.py [--output-dir DIR]
        [--chroma-dir DIR] [--bm25-file FILE]

The database URL is taken from ``$DATABASE_URL`` or ``DATABASE_URL`` in the
repository ``.env``; it is never printed.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "legalai-reconciliation-inventory-v1"
CATEGORIES = ("corpus", "admin_ingested", "test_pollution", "orphan")

TRUSTED_MANIFEST = REPO_ROOT / "data/structured/manifests/trusted_judgment_processing_manifest.json"
CHUNK_DIR = REPO_ROOT / "data/processed/judgment_chunks"
TEST_DIR = REPO_ROOT / "backend/scripts/tests"
SEED_USERS_SCRIPT = REPO_ROOT / "backend/scripts/seed_users.py"
DEVELOPMENT_MANIFESTS = (
    "development_judgments",
    "development_judgments_v2",
    "development_judgments_prescreen_v2",
    "balanced_development_judgments",
    "transition_validation_candidates",
)
BULK_CANDIDATES = REPO_ROOT / "data/processed/acquisition_runs/bulk_20260904_000000_stagea/candidates.json"
DEFAULT_CHROMA_DIR = REPO_ROOT / "chroma_store"
DEFAULT_BM25_FILE = REPO_ROOT / "bm25_store/legalai_trusted_judgments_bm25_v1.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/reconciliation"

UPLOAD_PREFIX = "data/raw/uploads/"
UPLOAD_NAME = re.compile(r"^[0-9a-f-]{36}_(?P<name>.+)$")
PG_CHUNK_ID = re.compile(r"^doc:(?P<doc>\d+):chunk:(?P<index>\d+)$")

# Fields compared between curated chunk files and each index's metadata.
PROVENANCE_FIELDS = (
    "document_id",
    "raw_sha256",
    "source_url",
    "chunk_index",
    "page_start",
    "page_end",
    "paragraph_start",
    "paragraph_end",
    "decision_year",
)
NULL_PAGE_FIELDS = ("page_start", "page_end")
# Fields a backfill must populate on PostgreSQL documents for the corpus.
PG_METADATA_FIELDS = (
    "decision_date",
    "court_name",
    "court_level",
    "case_number",
    "year",
    "source_url",
    "checksum",
    "case_disposition",
    "conviction_status",
    "appeal_result",
)
OUTCOME_FIELDS = ("case_disposition", "conviction_status", "appeal_result")
VALIDATOR_STATUS_PRECEDENCE = ("validated", "accepted", "needs_review", "downloaded", "pending")


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL" and value.strip():
                return value.strip().strip("'\"")
    raise SystemExit("DATABASE_URL is not set and not found in .env")


def manifest_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def load_curated_corpus() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (documents by document_id, chunks by chunk_id) for the curated set."""
    manifest = json.loads(TRUSTED_MANIFEST.read_text(encoding="utf-8"))
    documents = {row["document_id"]: row for row in manifest["documents"]}
    chunks: dict[str, dict[str, Any]] = {}
    for path in sorted(CHUNK_DIR.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            chunks[row["chunk_id"]] = row
    return documents, chunks


def test_literals() -> set[str]:
    """Every string constant in the test modules (fixture values)."""
    literals: set[str] = set()
    for path in sorted(TEST_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip():
                literals.add(node.value)
    return literals


def seed_emails() -> set[str]:
    text = SEED_USERS_SCRIPT.read_text(encoding="utf-8")
    return {match.lower() for match in re.findall(r'"email":\s*"([^"]+)"', text)}


def read_postgres(url: str) -> dict[str, list[dict[str, Any]]]:
    import psycopg2
    import psycopg2.extras

    queries = {
        "documents": (
            "SELECT id, doc_type, case_name, court_name, court_level, case_number, decision_date, year, "
            "case_disposition, conviction_status, appeal_result, source_url, file_path, checksum FROM documents ORDER BY id"
        ),
        "chunks": "SELECT id, document_id, chunk_index, chroma_id FROM chunks ORDER BY id",
        "document_sections": "SELECT document_id, count(*) AS n FROM document_sections GROUP BY document_id ORDER BY document_id",
        "users": "SELECT id, lower(email) AS email, role FROM users ORDER BY id",
        "ingestion_jobs": "SELECT id, status, document_id FROM ingestion_jobs ORDER BY id",
        "lawyer_verification_applications": "SELECT id, user_id, status FROM lawyer_verification_applications ORDER BY id",
        "query_history": "SELECT id, user_id, mode FROM query_history ORDER BY id",
        "email_verification_otps": "SELECT id, user_id FROM email_verification_otps ORDER BY id",
        "email_verification_tokens": "SELECT id, user_id FROM email_verification_tokens ORDER BY id",
        "database": "SELECT current_database() AS name",
    }
    connection = psycopg2.connect(url)
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()["transaction_read_only"] != "on":
                raise SystemExit("PostgreSQL session is not read-only; aborting.")
            result = {}
            for name, sql in queries.items():
                cursor.execute(sql)
                result[name] = [dict(row) for row in cursor.fetchall()]
        return result
    finally:
        connection.rollback()
        connection.close()


def read_chroma(chroma_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {collection_name: {"dimension": int, "embeddings": {id: metadata}}}."""
    database = chroma_dir / "chroma.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        collections: dict[str, dict[str, Any]] = {}
        for collection_id, name, dimension in connection.execute(
            "SELECT id, name, dimension FROM collections ORDER BY name"
        ):
            rows = connection.execute(
                """
                SELECT e.embedding_id, m.key, m.string_value, m.int_value, m.float_value, m.bool_value
                FROM embeddings e
                JOIN segments s ON s.id = e.segment_id
                LEFT JOIN embedding_metadata m ON m.id = e.id
                WHERE s.collection = ?
                ORDER BY e.embedding_id, m.key
                """,
                (collection_id,),
            )
            embeddings: dict[str, dict[str, Any]] = {}
            for embedding_id, key, string_value, int_value, float_value, bool_value in rows:
                metadata = embeddings.setdefault(embedding_id, {})
                if key is None:
                    continue
                value = next((v for v in (string_value, int_value, float_value, bool_value) if v is not None), None)
                metadata[key] = value
            collections[name] = {"dimension": dimension, "embeddings": embeddings}
        queue = Counter(
            (topic.rsplit("/", 1)[-1], operation)
            for topic, operation in connection.execute("SELECT topic, operation FROM embeddings_queue")
        )
        collection_ids = {
            row[0]: row[1] for row in connection.execute("SELECT id, name FROM collections")
        }
        queue_by_collection = {
            f"{collection_ids.get(topic, topic)}|op={operation}": count for (topic, operation), count in sorted(queue.items())
        }
        return {"collections": collections, "embeddings_queue": queue_by_collection}
    finally:
        connection.close()


def read_bm25(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = {record["chunk_id"]: record for record in data["records"]}
    metadata = {key: value for key, value in data["metadata"].items() if not isinstance(value, (list, dict))}
    return metadata, records


def read_json_vector_mirrors(chroma_dir: Path) -> dict[str, dict[str, Any]]:
    """JsonVectorStore files that sit next to the Chroma database."""
    mirrors = {}
    for path in sorted(chroma_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            records = {}
            for record in data["records"]:
                record_id = record.get("id") or record.get("chunk_id")
                records[record_id] = record.get("metadata") or {}
            mirrors[path.name] = {
                "metadata": {k: v for k, v in data.get("metadata", {}).items() if not isinstance(v, (list, dict))},
                "records": records,
            }
    return mirrors


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def upload_basename(file_path: str | None) -> str | None:
    if not file_path:
        return None
    if file_path.startswith(UPLOAD_PREFIX):
        name = file_path[len(UPLOAD_PREFIX):]
        match = UPLOAD_NAME.match(name)
        return match.group("name") if match else name
    return Path(file_path).name


def classify_pg_document(
    document: dict[str, Any],
    corpus_shas: set[str],
    corpus_urls: set[str],
    literals: set[str],
) -> tuple[str, str]:
    """Return (category, rule) for one PostgreSQL document."""
    checksum = document.get("checksum")
    if checksum and checksum in corpus_shas:
        return "corpus", "checksum matches a curated raw_sha256"
    if document.get("source_url") and document["source_url"] in corpus_urls:
        return "corpus", "source_url matches a curated source_url"
    basename = upload_basename(document.get("file_path"))
    fixture_values = [basename, document.get("case_name"), checksum]
    if any(value and value in literals for value in fixture_values):
        return "test_pollution", "file name, case name or checksum is a literal in backend/scripts/tests"
    if (document.get("file_path") or "").startswith(UPLOAD_PREFIX):
        return "admin_ingested", "file stored under data/raw/uploads by /ingest/upload"
    return "orphan", "no curated, upload or fixture source (store: postgres)"


def classify_index_entry(
    entry_id: str,
    curated_chunks: dict[str, dict[str, Any]],
    pg_document_categories: dict[int, str],
    store: str,
) -> tuple[str, str]:
    if entry_id in curated_chunks:
        return "corpus", "chunk_id is in the curated chunk files"
    match = PG_CHUNK_ID.match(entry_id)
    if match:
        document_id = int(match.group("doc"))
        category = pg_document_categories.get(document_id)
        if category is not None:
            return category, f"doc:<id> entry for postgres document classified {category}"
        return "orphan", f"doc:<id> entry with no postgres document (store: {store})"
    return "orphan", f"not a curated chunk and not a postgres doc:<id> entry (store: {store})"


def category_lists(assignments: dict[Any, str]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {category: [] for category in CATEGORIES}
    for key, category in assignments.items():
        grouped[category].append(key)
    return {category: sorted(values, key=lambda v: (str(type(v)), v)) for category, values in grouped.items()}


def store_summary(assignments: dict[Any, str], document_of: dict[Any, Any]) -> dict[str, Any]:
    by_category = Counter(assignments.values())
    documents_by_category: dict[str, set[Any]] = defaultdict(set)
    for key, category in assignments.items():
        documents_by_category[category].add(document_of.get(key))
    return {
        "total": len(assignments),
        "by_category": {category: by_category.get(category, 0) for category in CATEGORIES},
        "category_sum": sum(by_category.values()),
        "distinct_documents_by_category": {
            category: len(documents_by_category.get(category, set())) for category in CATEGORIES
        },
    }


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


def comparable(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def provenance_mismatches(
    curated_chunks: dict[str, dict[str, Any]],
    index_metadata: dict[str, dict[str, Any]],
    text_hash_of: dict[str, str | None],
) -> dict[str, Any]:
    field_mismatches: dict[str, list[str]] = defaultdict(list)
    missing_fields: dict[str, list[str]] = defaultdict(list)
    null_page_sentinels: Counter[str] = Counter()
    text_mismatches: list[str] = []
    for chunk_id in sorted(set(curated_chunks) & set(index_metadata)):
        source = curated_chunks[chunk_id]
        metadata = index_metadata[chunk_id]
        for field in PROVENANCE_FIELDS:
            if field not in metadata:
                missing_fields[field].append(chunk_id)
                continue
            # vector_store.metadata_for_chroma stores a null page as -1 with
            # has_page_provenance=False; readers map it back to None.
            if (
                field in NULL_PAGE_FIELDS
                and source.get(field) is None
                and comparable(metadata[field]) == -1
                and not metadata.get("has_page_provenance")
            ):
                null_page_sentinels[field] += 1
                continue
            if comparable(metadata[field]) != comparable(source.get(field)):
                field_mismatches[field].append(chunk_id)
        expected = sha256_text(source.get("chunk_text"))
        if chunk_id in text_hash_of and text_hash_of[chunk_id] != expected:
            text_mismatches.append(chunk_id)
    return {
        "field_value_mismatches": {field: ids for field, ids in sorted(field_mismatches.items())},
        "fields_absent_from_index_metadata": {field: len(ids) for field, ids in sorted(missing_fields.items())},
        "null_page_encoded_as_minus_one": dict(sorted(null_page_sentinels.items())),
        "chunk_text_hash_mismatches": text_mismatches,
    }


def validator_duplicates(curated_documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror validate_corpus.py: sha256 duplicated within one development manifest."""
    curated_by_source = {
        (doc["provider"], str(doc["source_document_id"])): doc["sha256"] for doc in curated_documents.values()
    }
    results = []
    for name in DEVELOPMENT_MANIFESTS:
        rows = manifest_rows(REPO_ROOT / f"data/structured/manifests/{name}.json")
        by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row.get("sha256"):
                by_sha[row["sha256"]].append(row)
        for sha, members in sorted(by_sha.items()):
            if len(members) < 2:
                continue
            described = []
            for row in members:
                key = (row.get("source_provider"), str(row.get("source_document_id")))
                described.append(
                    {
                        "local_id": row.get("local_id"),
                        "source_document_id": str(row.get("source_document_id")),
                        "status": row.get("status"),
                        "in_curated_corpus": curated_by_source.get(key) == sha,
                    }
                )
            described.sort(key=lambda item: item["local_id"] or "")
            in_corpus = [item for item in described if item["in_curated_corpus"]]

            def rank(item: dict[str, Any]) -> tuple[int, str]:
                status = item["status"] or ""
                order = VALIDATOR_STATUS_PRECEDENCE.index(status) if status in VALIDATOR_STATUS_PRECEDENCE else len(VALIDATOR_STATUS_PRECEDENCE)
                return order, item["local_id"] or ""

            if in_corpus:
                canonical, reason = in_corpus[0]["local_id"], "member whose source document is in the curated corpus"
            else:
                best = min(described, key=rank)
                canonical, reason = best["local_id"], "no member in curated corpus; best status by precedence"
            results.append(
                {
                    "manifest": f"data/structured/manifests/{name}.json",
                    "sha256": sha,
                    "record_count": len(members),
                    "members": described,
                    "canonical_candidate": canonical,
                    "canonical_reason": reason,
                }
            )
    return results


def acquisition_rows_by_source() -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    paths = [REPO_ROOT / f"data/structured/manifests/{name}.json" for name in DEVELOPMENT_MANIFESTS] + [BULK_CANDIDATES]
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    used = []
    for path in paths:
        if not path.exists():
            continue
        used.append(str(path.relative_to(REPO_ROOT)))
        for row in manifest_rows(path):
            if row.get("source_document_id") is not None:
                rows[str(row["source_document_id"])].append(row)
    return rows, used


def corpus_metadata_gaps(
    curated_documents: dict[str, dict[str, Any]],
    curated_chunks: dict[str, dict[str, Any]],
    pg_corpus_documents: dict[str, dict[str, Any]],
    section_rows_by_pg_document: dict[int, int],
) -> dict[str, Any]:
    acquisition, acquisition_sources = acquisition_rows_by_source()
    chunk_decision_date: dict[str, str] = {}
    for chunk in curated_chunks.values():
        if chunk.get("decision_date"):
            chunk_decision_date.setdefault(chunk["document_id"], chunk["decision_date"])

    def source_value(document: dict[str, Any], field: str) -> tuple[Any, str | None]:
        court = document.get("court") or {}
        rows = acquisition.get(str(document["source_document_id"]), [])
        if field == "decision_date":
            if document.get("decision_date"):
                return document["decision_date"], "trusted_manifest.decision_date"
            if chunk_decision_date.get(document["document_id"]):
                return chunk_decision_date[document["document_id"]], "chunk_files.decision_date"
            value = next((r.get("decision_date") for r in rows if r.get("decision_date")), None)
            return value, "acquisition_manifest.decision_date" if value else None
        if field == "court_name":
            return court.get("court_name"), "trusted_manifest.court.court_name" if court.get("court_name") else None
        if field == "court_level":
            return court.get("court_level"), "trusted_manifest.court.court_level" if court.get("court_level") else None
        if field == "year":
            value = document.get("decision_year")
            return value, "trusted_manifest.decision_year" if value else None
        if field == "source_url":
            return document.get("source_url"), "trusted_manifest.source_url" if document.get("source_url") else None
        if field == "checksum":
            return document.get("sha256"), "trusted_manifest.sha256" if document.get("sha256") else None
        if field == "case_number":
            value = next((r.get("case_number") for r in rows if r.get("case_number")), None)
            return value, "acquisition_manifest.case_number" if value else None
        return None, None  # outcome columns: no source exists

    per_field: dict[str, dict[str, Any]] = {}
    for field in PG_METADATA_FIELDS:
        missing_in_pg = []
        fillable: Counter[str] = Counter()
        no_source = []
        for document_id in sorted(curated_documents):
            pg_document = pg_corpus_documents.get(document_id)
            if pg_document is not None and pg_document.get(field) not in (None, ""):
                continue
            missing_in_pg.append(document_id)
            value, source = source_value(curated_documents[document_id], field)
            if value not in (None, "") and source:
                fillable[source] += 1
            else:
                no_source.append(document_id)
        per_field[field] = {
            "missing_in_postgres": len(missing_in_pg),
            "fillable_from_source": dict(sorted(fillable.items())),
            "no_source_count": len(no_source),
            "no_source_document_ids": no_source,
            "requires_n2_producer": field in OUTCOME_FIELDS,
        }

    detected_statutes = sum(
        1
        for document in curated_documents.values()
        if any(r.get("detected_statutes") for r in acquisition.get(str(document["source_document_id"]), []))
    )
    known_sections = sum(
        1
        for document in curated_documents.values()
        if any(r.get("known_sections") for r in acquisition.get(str(document["source_document_id"]), []))
    )
    return {
        "acquisition_sources_read": acquisition_sources,
        "fields": per_field,
        "document_sections": {
            "postgres_rows_for_corpus_documents": sum(
                section_rows_by_pg_document.get(document["id"], 0) for document in pg_corpus_documents.values()
            ),
            "documents_with_detected_statutes_in_acquisition_rows": detected_statutes,
            "documents_with_known_sections_in_acquisition_rows": known_sections,
            "requires_n2_producer": True,
        },
    }


def build_inventory(chroma_dir: Path, bm25_file: Path) -> dict[str, Any]:
    curated_documents, curated_chunks = load_curated_corpus()
    corpus_shas = {doc["sha256"] for doc in curated_documents.values() if doc.get("sha256")}
    corpus_urls = {doc["source_url"] for doc in curated_documents.values() if doc.get("source_url")}
    literals = test_literals()
    seeds = seed_emails()

    pg = read_postgres(database_url())
    chroma = read_chroma(chroma_dir)
    bm25_metadata, bm25_records = read_bm25(bm25_file)
    mirrors = read_json_vector_mirrors(chroma_dir)

    # PostgreSQL documents and chunks.
    pg_documents = {row["id"]: row for row in pg["documents"]}
    pg_document_category: dict[int, str] = {}
    pg_document_rule: dict[int, str] = {}
    for document_id, document in pg_documents.items():
        category, rule = classify_pg_document(document, corpus_shas, corpus_urls, literals)
        pg_document_category[document_id] = category
        pg_document_rule[document_id] = rule
    pg_chunk_category = {
        row["id"]: pg_document_category.get(row["document_id"], "orphan") for row in pg["chunks"]
    }
    pg_chunk_document = {row["id"]: row["document_id"] for row in pg["chunks"]}
    pg_chroma_ids = {row["chroma_id"]: row for row in pg["chunks"] if row.get("chroma_id")}

    pg_corpus_documents: dict[str, dict[str, Any]] = {}
    sha_to_document = {doc["sha256"]: document_id for document_id, doc in curated_documents.items()}
    for document_id, document in pg_documents.items():
        if pg_document_category[document_id] == "corpus":
            curated_id = sha_to_document.get(document.get("checksum") or "")
            if curated_id:
                pg_corpus_documents[curated_id] = document

    # Index stores.
    stores: dict[str, dict[str, Any]] = {}
    store_assignments: dict[str, dict[str, str]] = {}
    index_metadata_by_store: dict[str, dict[str, dict[str, Any]]] = {}
    text_hashes_by_store: dict[str, dict[str, str | None]] = {}

    for name, collection in sorted(chroma["collections"].items()):
        store = f"chroma:{name}"
        embeddings = collection["embeddings"]
        assignments = {
            entry_id: classify_index_entry(entry_id, curated_chunks, pg_document_category, store)[0]
            for entry_id in embeddings
        }
        store_assignments[store] = assignments
        index_metadata_by_store[store] = embeddings
        text_hashes_by_store[store] = {
            entry_id: sha256_text(metadata.get("chroma:document")) for entry_id, metadata in embeddings.items()
        }
        stores[store] = {
            **store_summary(assignments, {k: str(v.get("document_id")) for k, v in embeddings.items()}),
            "dimension": collection["dimension"],
        }

    bm25_store = "bm25:legalai_trusted_judgments_bm25_v1"
    bm25_assignments = {
        entry_id: classify_index_entry(entry_id, curated_chunks, pg_document_category, bm25_store)[0]
        for entry_id in bm25_records
    }
    store_assignments[bm25_store] = bm25_assignments
    bm25_metadata_flat = {
        entry_id: {"document_id": record.get("document_id"), **(record.get("metadata") or {})}
        for entry_id, record in bm25_records.items()
    }
    index_metadata_by_store[bm25_store] = bm25_metadata_flat
    text_hashes_by_store[bm25_store] = {entry_id: sha256_text(record.get("text")) for entry_id, record in bm25_records.items()}
    stores[bm25_store] = {
        **store_summary(bm25_assignments, {k: str(v.get("document_id")) for k, v in bm25_records.items()}),
        "index_metadata": bm25_metadata,
    }

    stores["postgres:documents"] = store_summary(pg_document_category, {k: k for k in pg_document_category})
    stores["postgres:chunks"] = store_summary(pg_chunk_category, pg_chunk_document)

    auxiliary_mirrors = {}
    for file_name, mirror in mirrors.items():
        store = f"json_mirror:chroma_store/{file_name}"
        assignments = {
            entry_id: classify_index_entry(entry_id, curated_chunks, pg_document_category, store)[0]
            for entry_id in mirror["records"]
        }
        auxiliary_mirrors[store] = {
            **store_summary(assignments, {k: str(v.get("document_id")) for k, v in mirror["records"].items()}),
            "index_metadata": mirror["metadata"],
            "missing_curated_chunk_ids": sorted(set(curated_chunks) - set(mirror["records"])),
        }

    # Exactly-once check: each store's entries are keys of one dict, so each
    # gets one label; verify the category sums equal the totals.
    exactly_once = {
        store: summary["category_sum"] == summary["total"] for store, summary in {**stores, **auxiliary_mirrors}.items()
    }

    # Cross-store mismatches.
    curated_chunk_ids = set(curated_chunks)
    mismatches: dict[str, Any] = {
        "corpus_chunks_missing_from_postgres": sorted(curated_chunk_ids - set(pg_chroma_ids)),
        "corpus_documents_missing_from_postgres": sorted(set(curated_documents) - set(pg_corpus_documents)),
    }
    for store, assignments in sorted(store_assignments.items()):
        ids = set(assignments)
        mismatches[f"corpus_chunks_missing_from_{store}"] = sorted(curated_chunk_ids - ids)
        non_corpus = {i for i, c in assignments.items() if c != "corpus"}
        mismatches[f"non_corpus_entries_in_{store}"] = {
            category: sorted(i for i in non_corpus if assignments[i] == category)
            for category in CATEGORIES
            if category != "corpus" and any(assignments[i] == category for i in non_corpus)
        }
        pg_ids_here = {i for i in ids if PG_CHUNK_ID.match(i)}
        mismatches[f"postgres_chunk_ids_missing_from_{store}"] = sorted(set(pg_chroma_ids) - pg_ids_here)
        mismatches[f"{store}_doc_ids_not_in_postgres_chunks"] = sorted(pg_ids_here - set(pg_chroma_ids))
        mismatches[f"corpus_provenance_vs_{store}"] = provenance_mismatches(
            curated_chunks, index_metadata_by_store[store], text_hashes_by_store[store]
        )
    main_ids = set(store_assignments.get("chroma:legalai_trusted_judgments_v1", {}))
    bm25_ids = set(bm25_assignments)
    mismatches["in_bm25_not_in_chroma_main"] = sorted(bm25_ids - main_ids)
    mismatches["in_chroma_main_not_in_bm25"] = sorted(main_ids - bm25_ids)
    per_document_chunk_counts = Counter(chunk["document_id"] for chunk in curated_chunks.values())
    for store, assignments in sorted(store_assignments.items()):
        metadata = index_metadata_by_store[store]
        counts = Counter(str(metadata[i].get("document_id")) for i, c in assignments.items() if c == "corpus")
        mismatches[f"corpus_document_chunk_count_mismatch_in_{store}"] = {
            document_id: {"expected": expected, "found": counts.get(document_id, 0)}
            for document_id, expected in sorted(per_document_chunk_counts.items())
            if counts.get(document_id, 0) != expected
        }

    # Duplicates.
    checksum_groups: dict[str, list[int]] = defaultdict(list)
    for document_id, document in pg_documents.items():
        if document.get("checksum"):
            checksum_groups[document["checksum"]].append(document_id)
    pg_duplicates = []
    for checksum, ids in sorted(checksum_groups.items()):
        if len(ids) < 2:
            continue
        corpus_ids = sorted(i for i in ids if pg_document_category[i] == "corpus")
        pg_duplicates.append(
            {
                "checksum": checksum,
                "document_ids": sorted(ids),
                "copies": len(ids),
                "extra_copies": len(ids) - 1,
                "categories": dict(Counter(pg_document_category[i] for i in ids)),
                "canonical_candidate": corpus_ids[0] if corpus_ids else None,
                "canonical_reason": (
                    "lowest-id corpus copy" if corpus_ids else "none: every copy is non-corpus; remove all copies"
                ),
            }
        )
    validator = validator_duplicates(curated_documents)

    # Non-corpus PostgreSQL tables (counts only; no emails are output).
    # Email domains used by test fixtures, e.g. "@example.test" in f-strings.
    test_domains = {
        literal.rsplit("@", 1)[1].lower()
        for literal in literals
        if "@" in literal and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]+", literal.rsplit("@", 1)[1])
    }

    def user_category(email: str | None) -> str:
        if not email:
            return "unknown"
        if email in seeds:
            return "seed_account"
        domain = email.rsplit("@", 1)[-1]
        if domain in test_domains or domain.endswith(".test"):
            return "test_fixture"
        return "unclassified"

    user_categories = {row["id"]: user_category(row["email"]) for row in pg["users"]}
    users_by_category = Counter(user_categories.values())
    users_by_category_role = Counter(f"{user_categories[row['id']]}|{row['role']}" for row in pg["users"])

    def by_user(table: str) -> dict[str, int]:
        return dict(sorted(Counter(user_categories.get(row["user_id"], "missing_user") for row in pg[table]).items()))

    jobs_by_status_and_document = Counter(
        f"{row['status']}|{pg_document_category.get(row['document_id'], 'no_document') if row['document_id'] else 'no_document'}"
        for row in pg["ingestion_jobs"]
    )
    application_pairs = Counter(
        f"{row['status']}|{user_categories.get(row['user_id'], 'missing_user')}" for row in pg["lawyer_verification_applications"]
    )

    inventory = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "postgres_database": pg["database"][0]["name"],
            "postgres_session": "read-only (transaction_read_only=on), rolled back",
            "chroma_sqlite": {
                "path": str((chroma_dir / "chroma.sqlite3").relative_to(REPO_ROOT)) if chroma_dir.is_relative_to(REPO_ROOT) else "chroma.sqlite3 (external copy)",
                "sha256": sha256_file(chroma_dir / "chroma.sqlite3"),
                "open_mode": "sqlite mode=ro&immutable=1",
            },
            "bm25_file": {
                "path": str(bm25_file.relative_to(REPO_ROOT)) if bm25_file.is_relative_to(REPO_ROOT) else bm25_file.name,
                "sha256": sha256_file(bm25_file),
            },
            "curated_manifest": {
                "path": str(TRUSTED_MANIFEST.relative_to(REPO_ROOT)),
                "sha256": sha256_file(TRUSTED_MANIFEST),
            },
            "curated_chunk_dir": str(CHUNK_DIR.relative_to(REPO_ROOT)),
            "curated_chunk_files_sha256": hashlib.sha256(
                "".join(f"{p.name}:{sha256_file(p)}\n" for p in sorted(CHUNK_DIR.glob("*.json"))).encode()
            ).hexdigest(),
        },
        "curated_corpus": {
            "documents": len(curated_documents),
            "chunks": len(curated_chunks),
            "documents_by_review_status": dict(sorted(Counter(d["human_review_status"] for d in curated_documents.values()).items())),
        },
        "stores": dict(sorted(stores.items())),
        "auxiliary_stores": dict(sorted(auxiliary_mirrors.items())),
        "exactly_once_category_sums_equal_totals": dict(sorted(exactly_once.items())),
        "classification": {
            "postgres:documents": category_lists(pg_document_category),
            "postgres:chunks": category_lists(pg_chunk_category),
            **{store: category_lists(assignments) for store, assignments in sorted(store_assignments.items())},
        },
        "classification_rules": {
            "postgres:documents": dict(sorted(Counter(f"{pg_document_category[i]}: {pg_document_rule[i]}" for i in pg_documents).items())),
            "postgres:chunks": "category of the parent postgres document; orphan if the parent is missing",
            "index entries": (
                "corpus if chunk_id is in the curated chunk files; doc:<id>:chunk:<n> takes the category of postgres "
                "document <id>; otherwise orphan (store named)"
            ),
        },
        "mismatches": mismatches,
        "duplicates": {
            "postgres_by_checksum": pg_duplicates,
            "postgres_documents_without_checksum": sorted(i for i, d in pg_documents.items() if not d.get("checksum")),
            "postgres_duplicate_rows_total": sum(group["extra_copies"] for group in pg_duplicates),
            "validator_manifest_duplicates": validator,
            "validator_duplicate_records_total": sum(group["record_count"] for group in validator),
        },
        "corpus_metadata_gaps": corpus_metadata_gaps(
            curated_documents,
            curated_chunks,
            pg_corpus_documents,
            {row["document_id"]: row["n"] for row in pg["document_sections"]},
        ),
        "non_document_tables": {
            "users_by_category": dict(sorted(users_by_category.items())),
            "users_by_category_and_role": dict(sorted(users_by_category_role.items())),
            "ingestion_jobs_by_status_and_document_category": dict(sorted(jobs_by_status_and_document.items())),
            "lawyer_verification_applications_by_status_and_user_category": dict(sorted(application_pairs.items())),
            "query_history_by_user_category": by_user("query_history"),
            "email_verification_otps_by_user_category": by_user("email_verification_otps"),
            "email_verification_tokens_by_user_category": by_user("email_verification_tokens"),
            "document_sections_rows": sum(row["n"] for row in pg["document_sections"]),
        },
        "chroma_embeddings_queue": chroma["embeddings_queue"],
    }
    return inventory


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def render_report(inventory: dict[str, Any]) -> str:
    lines = [
        "# Reconciliation Inventory Report",
        "",
        "Generated by `backend/scripts/reconcile_inventory.py` from read-only access to PostgreSQL, Chroma (SQLite",
        "`mode=ro&immutable=1`) and the BM25 file. IDs, hashes and counts only. Full detail is in `inventory.json`.",
        "",
        f"- Schema: `{inventory['schema_version']}`",
        f"- PostgreSQL database: `{inventory['inputs']['postgres_database']}`",
        f"- Curated corpus: {inventory['curated_corpus']['documents']} documents, {inventory['curated_corpus']['chunks']} chunks "
        f"(`{inventory['inputs']['curated_manifest']['path']}`)",
        "",
        "## Per-store classification",
        "",
        "| Store | Total | corpus | admin_ingested | test_pollution | orphan | Sum = total |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for store, summary in {**inventory["stores"], **inventory["auxiliary_stores"]}.items():
        counts = summary["by_category"]
        lines.append(
            f"| `{store}` | {summary['total']} | {counts['corpus']} | {counts['admin_ingested']} | "
            f"{counts['test_pollution']} | {counts['orphan']} | {'yes' if summary['category_sum'] == summary['total'] else 'NO'} |"
        )
    lines += [
        "",
        "`json_mirror:*` rows are JsonVectorStore files inside `chroma_store/` (mock-embedding builds). They are not",
        "read by the query path and are listed for completeness.",
        "",
        "Distinct documents per category:",
        "",
        "| Store | corpus | admin_ingested | test_pollution | orphan |",
        "|---|---:|---:|---:|---:|",
    ]
    for store, summary in inventory["stores"].items():
        docs = summary["distinct_documents_by_category"]
        lines.append(f"| `{store}` | {docs['corpus']} | {docs['admin_ingested']} | {docs['test_pollution']} | {docs['orphan']} |")

    mismatches = inventory["mismatches"]
    lines += ["", "## Cross-store mismatches", ""]
    lines.append(f"- Corpus documents missing from PostgreSQL: **{len(mismatches['corpus_documents_missing_from_postgres'])}**")
    lines.append(f"- Corpus chunks missing from PostgreSQL: **{len(mismatches['corpus_chunks_missing_from_postgres'])}**")
    for key, value in mismatches.items():
        if key.startswith("corpus_chunks_missing_from_") and key != "corpus_chunks_missing_from_postgres":
            lines.append(f"- Corpus chunks missing from `{key.removeprefix('corpus_chunks_missing_from_')}`: {len(value)}")
    for key, value in mismatches.items():
        if key.startswith("non_corpus_entries_in_") and value:
            store = key.removeprefix("non_corpus_entries_in_")
            parts = ", ".join(f"{category}: {', '.join(f'`{i}`' for i in ids)}" for category, ids in value.items())
            lines.append(f"- Non-corpus entries in `{store}`: {parts}")
    for key, value in mismatches.items():
        if key.startswith("postgres_chunk_ids_missing_from_") and value:
            lines.append(f"- PostgreSQL chunk ids missing from `{key.removeprefix('postgres_chunk_ids_missing_from_')}`: {len(value)}")
        if key.endswith("_doc_ids_not_in_postgres_chunks") and value:
            store = key.removesuffix("_doc_ids_not_in_postgres_chunks")
            lines.append(f"- `{store}` doc:<id> entries with no PostgreSQL chunk row: {', '.join(f'`{i}`' for i in value)}")
    lines.append(f"- In BM25 but not in the main Chroma collection: {', '.join(f'`{i}`' for i in mismatches['in_bm25_not_in_chroma_main']) or 'none'}")
    lines.append(f"- In the main Chroma collection but not in BM25: {', '.join(f'`{i}`' for i in mismatches['in_chroma_main_not_in_bm25']) or 'none'}")
    for key, value in mismatches.items():
        if key.startswith("corpus_document_chunk_count_mismatch_in_") and value:
            lines.append(f"- Corpus documents with wrong chunk counts in `{key.removeprefix('corpus_document_chunk_count_mismatch_in_')}`: {len(value)}")
    lines += ["", "Provenance of corpus chunks against each index (curated chunk files are the reference):", ""]
    lines += [
        "| Store | Field value mismatches | Fields absent from index metadata | Null page stored as -1 | Text hash mismatches |",
        "|---|---|---|---|---:|",
    ]
    for key, value in mismatches.items():
        if key.startswith("corpus_provenance_vs_"):
            store = key.removeprefix("corpus_provenance_vs_")
            fields = ", ".join(f"{f}: {len(ids)}" for f, ids in value["field_value_mismatches"].items()) or "none"
            absent = ", ".join(f"{f}: {n}" for f, n in value["fields_absent_from_index_metadata"].items()) or "none"
            sentinel = ", ".join(f"{f}: {n}" for f, n in value["null_page_encoded_as_minus_one"].items()) or "none"
            lines.append(f"| `{store}` | {fields} | {absent} | {sentinel} | {len(value['chunk_text_hash_mismatches'])} |")
    lines += [
        "",
        "Null pages stored as `-1` follow `vector_store.metadata_for_chroma` (with `has_page_provenance=False`) and are",
        "not mismatches.",
    ]

    duplicates = inventory["duplicates"]
    lines += ["", "## Duplicates", "", "PostgreSQL documents by checksum:", ""]
    lines += ["| Checksum | Copies | Categories | Canonical candidate |", "|---|---:|---|---|"]
    for group in duplicates["postgres_by_checksum"]:
        categories = ", ".join(f"{k}: {v}" for k, v in group["categories"].items())
        lines.append(f"| `{group['checksum']}` | {group['copies']} | {categories} | {group['canonical_candidate'] or '—'} ({group['canonical_reason']}) |")
    lines.append("")
    lines.append(
        f"Duplicate rows beyond the first copy: **{duplicates['postgres_duplicate_rows_total']}**. "
        f"PostgreSQL documents with no checksum: {len(duplicates['postgres_documents_without_checksum'])}."
    )
    lines += ["", "Validator duplicates (sha256 repeated within one development manifest, as `validate_corpus.py` counts them):", ""]
    lines += ["| Manifest | sha256 | Records | Members (local_id: status, in corpus) | Canonical candidate |", "|---|---|---:|---|---|"]
    for group in duplicates["validator_manifest_duplicates"]:
        members = "; ".join(f"{m['local_id']}: {m['status']}, {'yes' if m['in_curated_corpus'] else 'no'}" for m in group["members"])
        lines.append(f"| `{group['manifest'].rsplit('/', 1)[-1]}` | `{group['sha256'][:16]}…` | {group['record_count']} | {members} | {group['canonical_candidate']} ({group['canonical_reason']}) |")
    lines.append("")
    lines.append(f"Validator duplicate records in total: **{duplicates['validator_duplicate_records_total']}**.")

    gaps = inventory["corpus_metadata_gaps"]
    lines += ["", "## PostgreSQL metadata gaps for corpus documents", ""]
    lines += ["| Field | Missing in PG | Fillable from source | No source | Needs N2 |", "|---|---:|---|---:|---|"]
    for field, info in gaps["fields"].items():
        fillable = ", ".join(f"{source}: {count}" for source, count in info["fillable_from_source"].items()) or "—"
        lines.append(f"| `{field}` | {info['missing_in_postgres']} | {fillable} | {info['no_source_count']} | {'yes' if info['requires_n2_producer'] else 'no'} |")
    sections = gaps["document_sections"]
    lines += [
        "",
        f"`document_sections`: no rows for corpus documents. Acquisition rows carry `detected_statutes` for "
        f"{sections['documents_with_detected_statutes_in_acquisition_rows']} documents and `known_sections` for "
        f"{sections['documents_with_known_sections_in_acquisition_rows']}; a section producer (N2) is required.",
        "",
        "Acquisition sources read: " + ", ".join(f"`{p}`" for p in gaps["acquisition_sources_read"]) + ".",
        "",
        "## Other PostgreSQL tables (counts only)",
        "",
    ]
    for key, value in inventory["non_document_tables"].items():
        if isinstance(value, dict):
            lines.append(f"- `{key}`: " + ", ".join(f"{k}: {v}" for k, v in value.items()))
        else:
            lines.append(f"- `{key}`: {value}")
    lines += ["", "## Chroma embeddings queue", ""]
    lines.append(
        "Rows in Chroma's internal `embeddings_queue` by collection and operation (informational): "
        + (", ".join(f"{k}: {v}" for k, v in inventory["chroma_embeddings_queue"].items()) or "none")
        + "."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--bm25-file", type=Path, default=DEFAULT_BM25_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    inventory = build_inventory(args.chroma_dir.resolve(), args.bm25_file.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output_dir / "INVENTORY_REPORT.md").write_text(render_report(inventory), encoding="utf-8")

    failed = [store for store, ok in inventory["exactly_once_category_sums_equal_totals"].items() if not ok]
    for store, summary in {**inventory["stores"], **inventory["auxiliary_stores"]}.items():
        counts = " ".join(f"{k}={v}" for k, v in summary["by_category"].items())
        print(f"{store}: total={summary['total']} {counts}")
    print(f"wrote {output_dir / 'inventory.json'} and {output_dir / 'INVENTORY_REPORT.md'}")
    if failed:
        print(f"category sums do not equal totals for: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
