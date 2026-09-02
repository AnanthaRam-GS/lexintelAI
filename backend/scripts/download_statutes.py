"""Download official statutory corpus files from the development manifest."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import (  # noqa: E402
    file_size,
    find_duplicate_by_sha256,
    load_manifest,
    sha256_file,
    write_manifest_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
STATUTES_MANIFEST = REPO_ROOT / "data/structured/manifests/statutes.json"
CORPUS_DOCUMENTS_MANIFEST = (
    REPO_ROOT / "data/structured/manifests/corpus_documents.json"
)
RAW_STATUTES_DIR = REPO_ROOT / "data/raw/statutes"
USER_AGENT = "LegalAI corpus foundation/0.1"


def is_explicit_official_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.endswith("indiacode.nic.in")
        and parsed.path.lower().endswith(".pdf")
    )


def destination_for(entry: dict[str, Any]) -> Path:
    return RAW_STATUTES_DIR / entry["short_name"] / entry["expected_filename"]


def build_metadata_record(
    entry: dict[str, Any],
    destination: Path,
    retrieved_at: datetime,
) -> dict[str, Any]:
    digest = sha256_file(destination)
    return {
        "document_id": entry["id"],
        "document_type": entry["document_type"],
        "title": entry["title"],
        "case_name": None,
        "case_number": None,
        "court_name": None,
        "court_level": None,
        "decision_date": None,
        "year": None,
        "statute_name": entry["title"],
        "source_provider": entry["source_provider"],
        "source_url": entry["source_url"],
        "source_document_id": entry["id"],
        "source_retrieved_at": retrieved_at.isoformat(),
        "source_license_or_terms": entry.get("source_license_or_terms"),
        "attribution_required": entry["attribution_required"],
        "attribution_text": entry.get("attribution_text"),
        "raw_file_path": str(destination.relative_to(REPO_ROOT)),
        "sha256": digest,
        "file_size_bytes": file_size(destination),
        "mime_type": "application/pdf",
        "language": entry.get("language", "en"),
        "notes": entry.get("notes"),
    }


def download_pdf(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status < 200 or status >= 300:
            raise RuntimeError(f"HTTP status {status}")
        content = response.read()
    if not content:
        raise RuntimeError("downloaded content is empty")
    if not content.startswith(b"%PDF"):
        raise RuntimeError("downloaded content does not start with PDF magic header")
    return content


def upsert_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    for index, existing in enumerate(records):
        if existing.get("document_id") == record["document_id"]:
            records[index] = record
            return
    records.append(record)


def run(dry_run: bool, force: bool, timeout: int) -> int:
    statutes = load_manifest(STATUTES_MANIFEST)
    corpus_records = load_manifest(CORPUS_DOCUMENTS_MANIFEST)
    failures = 0

    for entry in statutes:
        destination = destination_for(entry)
        url = entry["source_url"]
        explicit_pdf = is_explicit_official_pdf_url(url)
        print(f"{entry['short_name']}: {entry['title']}")
        print(f"  destination: {destination.relative_to(REPO_ROOT)}")

        if not explicit_pdf:
            print("  skipped: source_url is not a verified official PDF URL")
            continue

        if dry_run:
            print("  dry-run: would download official PDF")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not force:
            digest = sha256_file(destination)
            print(f"  exists: sha256={digest}")
            continue

        try:
            content = download_pdf(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            failures += 1
            print(f"  failed: {exc}", file=sys.stderr)
            continue

        tmp_path = destination.with_suffix(destination.suffix + ".tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(destination)

        record = build_metadata_record(entry, destination, datetime.now(UTC))
        duplicate = find_duplicate_by_sha256(record["sha256"], corpus_records)
        if duplicate and duplicate.get("document_id") != record["document_id"]:
            print(
                "  warning: duplicate sha256 matches "
                f"{duplicate.get('document_id')}",
                file=sys.stderr,
            )
        upsert_record(corpus_records, record)
        write_manifest_atomic(CORPUS_DOCUMENTS_MANIFEST, corpus_records)
        print(
            "  downloaded: "
            f"sha256={record['sha256']} size={record['file_size_bytes']}"
        )

    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(dry_run=args.dry_run, force=args.force, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
