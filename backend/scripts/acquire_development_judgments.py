"""Controlled Indian Kanoon acquisition for the small development corpus."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import (  # noqa: E402
    file_size,
    find_duplicate_by_sha256,
    load_manifest,
    safe_filename,
    sha256_file,
    write_manifest_atomic,
)
from backend.scripts.env_utils import load_project_env  # noqa: E402
from backend.scripts.indiankanoon_client import (  # noqa: E402
    IndianKanoonClient,
    IndianKanoonClientError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
QUERY_MANIFEST = MANIFEST_DIR / "development_judgment_queries.json"
JUDGMENT_MANIFEST = MANIFEST_DIR / "development_judgments.json"
REVIEW_MANIFEST = MANIFEST_DIR / "development_judgment_review.json"
RAW_DIR = REPO_ROOT / "data/raw/judgments/indiankanoon"
DEFAULT_LIMIT = 5
MAX_LIMIT = 50
ATTRIBUTION_TEXT = "Judgment data sourced from Indian Kanoon API."
VALID_COURT_LEVELS = {
    "supreme_court",
    "high_court",
    "district_or_sessions",
    "other",
    "unknown",
}


class AcquisitionConfigError(ValueError):
    """Raised when acquisition configuration is invalid."""


def validate_limit(limit: int) -> int:
    if limit < 1:
        raise AcquisitionConfigError("limit must be at least 1")
    if limit > MAX_LIMIT:
        raise AcquisitionConfigError(f"limit must not exceed {MAX_LIMIT}")
    return limit


def normalize_court_level(court_name: str | None) -> str:
    if not court_name:
        return "unknown"
    normalized = court_name.lower()
    if "supreme court" in normalized:
        return "supreme_court"
    if "high court" in normalized:
        return "high_court"
    if "sessions" in normalized or "session court" in normalized:
        return "district_or_sessions"
    if "district court" in normalized or "district judge" in normalized:
        return "district_or_sessions"
    if "court" in normalized or "tribunal" in normalized:
        return "other"
    return "unknown"


def parse_year(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    for index in range(max(len(text) - 3, 0)):
        candidate = text[index : index + 4]
        if candidate.isdigit():
            year = int(candidate)
            if 1800 <= year <= date.today().year + 1:
                return year
    return None


def extract_results(search_response: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("docs", "results", "result", "matches"):
        value = search_response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def extract_source_document_id(result: dict[str, Any]) -> str | None:
    for key in ("tid", "docid", "doc_id", "id"):
        value = result.get(key)
        if value is not None:
            return str(value)
    return None


def extract_case_name(result: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    for source in (metadata, result):
        for key in ("title", "doc_title", "case_name"):
            value = source.get(key)
            if value:
                return str(value)
    return None


def extract_court_name(result: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    for source in (metadata, result):
        for key in ("court", "court_name", "docsource"):
            value = source.get(key)
            if value:
                return str(value)
    return None


def extension_for_content(content: bytes, mime_type: str | None) -> str:
    if content.startswith(b"%PDF"):
        return ".pdf"
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type.split(";")[0].strip())
        if guessed:
            return guessed
    sample = content[:128].lstrip().lower()
    if sample.startswith(b"<!doctype html") or sample.startswith(b"<html"):
        return ".html"
    return ".bin"


def normalize_original_document_payload(payload: bytes) -> tuple[bytes, str]:
    """Return actual document bytes and MIME type from Indian Kanoon origdoc."""

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        mime_type = "application/pdf" if payload.startswith(b"%PDF") else "application/octet-stream"
        return payload, mime_type

    if not isinstance(parsed, dict) or "doc" not in parsed:
        return payload, "application/json"

    encoded_doc = parsed.get("doc")
    if not isinstance(encoded_doc, str):
        return payload, "application/json"

    try:
        content = base64.b64decode(encoded_doc, validate=True)
    except ValueError:
        return payload, "application/json"

    mime_type = str(parsed.get("Content-Type") or parsed.get("content_type") or "").strip()
    if not mime_type:
        mime_type = "application/pdf" if content.startswith(b"%PDF") else "application/octet-stream"
    return content, mime_type


def source_id_exists(source_document_id: str, records: list[dict[str, Any]]) -> bool:
    return any(
        record.get("source_provider") == "indian_kanoon"
        and str(record.get("source_document_id")) == source_document_id
        for record in records
    )


def active_record_count(records: list[dict[str, Any]]) -> int:
    return sum(
        1
        for record in records
        if record.get("status") in {"downloaded", "validated"}
    )


def should_stop_for_api_error(exc: IndianKanoonClientError) -> bool:
    return exc.status_code in {401, 403, 429}


def review_record_for(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": record["local_id"],
        "source_document_id": record["source_document_id"],
        "case_name": record["case_name"],
        "offence_family": record["offence_family"],
        "source_url": record["source_url"],
        "automated_status": record["status"],
        "human_review_status": "pending",
        "review_notes": None,
    }


def upsert_by_local_id(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    for index, existing in enumerate(records):
        if existing.get("local_id") == record["local_id"]:
            records[index] = record
            return
    records.append(record)


def acquire(limit: int, dry_run: bool, query_id: str | None = None, delay: float = 1.0) -> int:
    validate_limit(limit)
    queries = load_manifest(QUERY_MANIFEST)
    if query_id:
        queries = [query for query in queries if query.get("query_id") == query_id]
        if not queries:
            raise AcquisitionConfigError(f"unknown query_id: {query_id}")

    if dry_run:
        print(f"Dry run: {len(queries)} query groups configured")
        print(f"Maximum acquisitions this run: {limit}")
        for query in queries:
            print(f"- {query['query_id']}: target {query['target_count']} {query['offence_family']}")
        print("No Indian Kanoon API requests were made.")
        return 0

    if not os.getenv("INDIAN_KANOON_API_TOKEN"):
        print("Indian Kanoon API token is not configured.", file=sys.stderr)
        return 2

    records = load_manifest(JUDGMENT_MANIFEST)
    review_records = load_manifest(REVIEW_MANIFEST)
    starting_active_count = active_record_count(records)
    if starting_active_count >= limit:
        print(f"Corpus already has {starting_active_count} active development judgments.")
        return 0
    client = IndianKanoonClient()
    acquired = 0

    for query in queries:
        if starting_active_count + acquired >= limit:
            break
        try:
            search_response = client.search(str(query["query"]), page=0)
        except IndianKanoonClientError as exc:
            print(f"{query['query_id']}: search failed: {exc}", file=sys.stderr)
            if should_stop_for_api_error(exc):
                return 1
            continue
        time.sleep(delay)

        for rank, result in enumerate(extract_results(search_response), start=1):
            if starting_active_count + acquired >= limit:
                break
            source_document_id = extract_source_document_id(result)
            if not source_document_id:
                continue
            if source_id_exists(source_document_id, records):
                continue

            try:
                metadata = client.get_document_metadata(source_document_id)
            except IndianKanoonClientError as exc:
                print(f"{source_document_id}: metadata failed: {exc}", file=sys.stderr)
                if should_stop_for_api_error(exc):
                    return 1
                continue
            time.sleep(delay)

            case_name = extract_case_name(result, metadata)
            court_name = extract_court_name(result, metadata)
            year = parse_year(metadata.get("date") or result.get("date") or case_name)

            try:
                payload = client.get_original_document(source_document_id)
            except IndianKanoonClientError as exc:
                print(f"{source_document_id}: original document failed: {exc}", file=sys.stderr)
                if should_stop_for_api_error(exc):
                    return 1
                continue
            time.sleep(delay)

            content, mime_type = normalize_original_document_payload(payload)
            extension = extension_for_content(content, mime_type)
            name_part = safe_filename(case_name or source_document_id)
            raw_path = RAW_DIR / f"{safe_filename(source_document_id)}_{name_part}{extension}"
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            if raw_path.exists():
                existing_digest = sha256_file(raw_path)
                import hashlib

                incoming_digest = hashlib.sha256(content).hexdigest()
                if existing_digest != incoming_digest:
                    print(
                        f"{source_document_id}: local file exists with different content",
                        file=sys.stderr,
                    )
                    continue
            else:
                raw_path.write_bytes(content)
            digest = sha256_file(raw_path)

            duplicate = find_duplicate_by_sha256(digest, records)
            if duplicate is not None:
                raw_path.unlink(missing_ok=True)
                excluded = {
                    "local_id": f"dev-{source_document_id}",
                    "source_provider": "indian_kanoon",
                    "source_document_id": source_document_id,
                    "source_url": f"https://indiankanoon.org/doc/{source_document_id}/",
                    "case_name": case_name,
                    "case_number": None,
                    "court_name": court_name,
                    "court_level": normalize_court_level(court_name),
                    "decision_date": metadata.get("date"),
                    "year": year,
                    "legal_regime": "unknown",
                    "offence_family": query["offence_family"],
                    "known_sections": [],
                    "acquisition_query": query["query"],
                    "retrieval_rank": rank,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "raw_file_path": None,
                    "sha256": digest,
                    "file_size_bytes": None,
                    "mime_type": mime_type,
                    "attribution_required": True,
                    "attribution_text": ATTRIBUTION_TEXT,
                    "status": "excluded_duplicate",
                    "notes": f"Duplicate SHA-256 of {duplicate.get('local_id')}",
                }
                upsert_by_local_id(records, excluded)
                continue

            status = "validated" if raw_path.stat().st_size > 0 else "failed"
            record = {
                "local_id": f"dev-{source_document_id}",
                "source_provider": "indian_kanoon",
                "source_document_id": source_document_id,
                "source_url": f"https://indiankanoon.org/doc/{source_document_id}/",
                "case_name": case_name,
                "case_number": None,
                "court_name": court_name,
                "court_level": normalize_court_level(court_name),
                "decision_date": metadata.get("date"),
                "year": year,
                "legal_regime": "unknown",
                "offence_family": query["offence_family"],
                "known_sections": [],
                "acquisition_query": query["query"],
                "retrieval_rank": rank,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "raw_file_path": str(raw_path.relative_to(REPO_ROOT)),
                "sha256": digest,
                "file_size_bytes": file_size(raw_path),
                "mime_type": mime_type,
                "attribution_required": True,
                "attribution_text": ATTRIBUTION_TEXT,
                "status": status,
                "notes": None,
            }
            upsert_by_local_id(records, record)
            upsert_by_local_id(review_records, review_record_for(record))
            acquired += 1

    write_manifest_atomic(JUDGMENT_MANIFEST, records)
    write_manifest_atomic(REVIEW_MANIFEST, review_records)
    print(f"Acquired {acquired} development judgments.")
    print(f"Active development corpus size: {starting_active_count + acquired}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--query-id")
    parser.add_argument("--delay", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    try:
        return acquire(
            limit=args.limit,
            dry_run=args.dry_run,
            query_id=args.query_id,
            delay=args.delay,
        )
    except AcquisitionConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
