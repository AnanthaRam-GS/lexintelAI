"""Validate local LegalAI corpus manifests and raw document integrity."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest, sha256_file  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
STATUTES_MANIFEST = MANIFEST_DIR / "statutes.json"
CORPUS_DOCUMENTS_MANIFEST = MANIFEST_DIR / "corpus_documents.json"
DEVELOPMENT_JUDGMENTS_MANIFEST = MANIFEST_DIR / "development_judgments.json"
REQUIRED_FIELDS = {
    "document_id",
    "document_type",
    "title",
    "source_provider",
    "source_url",
    "source_retrieved_at",
    "attribution_required",
    "raw_file_path",
    "sha256",
    "file_size_bytes",
    "mime_type",
}
DEVELOPMENT_REQUIRED_FIELDS = {
    "local_id",
    "source_provider",
    "source_document_id",
    "source_url",
    "case_name",
    "court_level",
    "year",
    "offence_family",
    "raw_file_path",
    "sha256",
    "file_size_bytes",
    "mime_type",
    "attribution_required",
    "status",
}
VALID_DEVELOPMENT_STATUSES = {
    "planned",
    "metadata_retrieved",
    "downloaded",
    "validated",
    "failed",
    "excluded_duplicate",
    "excluded_irrelevant",
}
VALID_COURT_LEVELS = {
    "supreme_court",
    "high_court",
    "district_or_sessions",
    "other",
    "unknown",
}


def validate_json_manifest(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        return load_manifest(path)
    except Exception as exc:
        errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
        return []


def validate_document_records(records: list[dict[str, Any]]) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    duplicate_count = 0
    sha_counts = Counter(record.get("sha256") for record in records if record.get("sha256"))
    provider_doc_ids: dict[tuple[str, str], list[str]] = defaultdict(list)

    for record in records:
        record_id = str(record.get("document_id", "<missing>"))
        missing = sorted(field for field in REQUIRED_FIELDS if field not in record)
        if missing:
            errors.append(f"{record_id}: missing required fields: {', '.join(missing)}")

        source_url = record.get("source_url")
        if not source_url:
            errors.append(f"{record_id}: missing source_url")

        source_provider = record.get("source_provider")
        if not source_provider:
            errors.append(f"{record_id}: missing source_provider")

        if record.get("attribution_required") is True and not record.get("attribution_text"):
            errors.append(f"{record_id}: attribution required but attribution_text is missing")

        source_document_id = record.get("source_document_id")
        if source_provider and source_document_id:
            provider_doc_ids[(str(source_provider), str(source_document_id))].append(record_id)

        raw_file_path = record.get("raw_file_path")
        if not raw_file_path:
            continue
        raw_path = REPO_ROOT / str(raw_file_path)
        if not raw_path.exists():
            errors.append(f"{record_id}: referenced raw file does not exist: {raw_file_path}")
            continue

        actual_sha = sha256_file(raw_path)
        if record.get("sha256") != actual_sha:
            errors.append(f"{record_id}: sha256 mismatch for {raw_file_path}")

        actual_size = raw_path.stat().st_size
        if record.get("file_size_bytes") != actual_size:
            errors.append(f"{record_id}: file_size_bytes mismatch for {raw_file_path}")

        suffix = raw_path.suffix.lower()
        mime_type = record.get("mime_type")
        if suffix == ".pdf" and mime_type != "application/pdf":
            errors.append(f"{record_id}: PDF extension with non-PDF mime_type")
        if mime_type == "application/pdf":
            with raw_path.open("rb") as file_obj:
                header = file_obj.read(7)
                if not (header.startswith(b"%PDF") or header.startswith(b"\xef\xbb\xbf%PDF")):
                    errors.append(f"{record_id}: PDF record missing PDF magic header")
            if suffix != ".pdf":
                warnings.append(f"{record_id}: PDF mime_type but file extension is not .pdf")

    for sha, count in sha_counts.items():
        if count > 1:
            duplicate_count += count
            warnings.append(f"duplicate sha256 {sha}: {count} records")

    for (provider, source_id), record_ids in provider_doc_ids.items():
        if len(record_ids) > 1:
            errors.append(
                "duplicate source_document_id for provider "
                f"{provider}/{source_id}: {', '.join(record_ids)}"
            )

    return errors, warnings, duplicate_count


def validate_development_judgments(
    records: list[dict[str, Any]],
) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    duplicate_count = 0
    sha_counts = Counter(record.get("sha256") for record in records if record.get("sha256"))
    provider_doc_ids: dict[tuple[str, str], list[str]] = defaultdict(list)

    for record in records:
        record_id = str(record.get("local_id", "<missing>"))
        missing = sorted(field for field in DEVELOPMENT_REQUIRED_FIELDS if field not in record)
        if missing:
            errors.append(f"{record_id}: missing required fields: {', '.join(missing)}")

        status = record.get("status")
        if status not in VALID_DEVELOPMENT_STATUSES:
            errors.append(f"{record_id}: invalid status: {status}")

        source_provider = record.get("source_provider")
        source_document_id = record.get("source_document_id")
        if not source_document_id:
            errors.append(f"{record_id}: missing source_document_id")
        if not record.get("source_url"):
            errors.append(f"{record_id}: missing source_url")
        if source_provider and source_document_id:
            provider_doc_ids[(str(source_provider), str(source_document_id))].append(record_id)

        court_level = record.get("court_level")
        if court_level not in VALID_COURT_LEVELS:
            errors.append(f"{record_id}: invalid court_level: {court_level}")

        year = record.get("year")
        if year is not None and (not isinstance(year, int) or year < 1800 or year > 2100):
            errors.append(f"{record_id}: invalid year: {year}")

        if source_provider == "indian_kanoon" and record.get("attribution_required") is not True:
            errors.append(f"{record_id}: Indian Kanoon record must require attribution")
        if record.get("attribution_required") is True and not record.get("attribution_text"):
            errors.append(f"{record_id}: attribution required but attribution_text is missing")

        raw_file_path = record.get("raw_file_path")
        if status in {"downloaded", "validated"} and not raw_file_path:
            errors.append(f"{record_id}: {status} record missing raw_file_path")
        if not raw_file_path:
            continue

        raw_path = REPO_ROOT / str(raw_file_path)
        if not raw_path.exists():
            errors.append(f"{record_id}: referenced raw file does not exist: {raw_file_path}")
            continue
        if raw_path.stat().st_size == 0:
            errors.append(f"{record_id}: raw file is zero bytes")

        actual_sha = sha256_file(raw_path)
        if record.get("sha256") != actual_sha:
            errors.append(f"{record_id}: sha256 mismatch for {raw_file_path}")
        if record.get("file_size_bytes") != raw_path.stat().st_size:
            errors.append(f"{record_id}: file_size_bytes mismatch for {raw_file_path}")

        suffix = raw_path.suffix.lower()
        mime_type = record.get("mime_type")
        if suffix == ".pdf" and mime_type != "application/pdf":
            errors.append(f"{record_id}: PDF extension with non-PDF mime_type")
        if mime_type == "application/pdf":
            with raw_path.open("rb") as file_obj:
                header = file_obj.read(7)
                if not (header.startswith(b"%PDF") or header.startswith(b"\xef\xbb\xbf%PDF")):
                    errors.append(f"{record_id}: PDF record missing PDF magic header")

    for sha, count in sha_counts.items():
        if count > 1:
            duplicate_count += count
            warnings.append(f"duplicate development judgment sha256 {sha}: {count} records")

    for (provider, source_id), record_ids in provider_doc_ids.items():
        if len(record_ids) > 1:
            errors.append(
                "duplicate development source_document_id for provider "
                f"{provider}/{source_id}: {', '.join(record_ids)}"
            )

    return errors, warnings, duplicate_count


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    validate_json_manifest(STATUTES_MANIFEST, errors)
    records = validate_json_manifest(CORPUS_DOCUMENTS_MANIFEST, errors)
    if not CORPUS_DOCUMENTS_MANIFEST.exists():
        warnings.append("corpus_documents.json does not exist yet; no documents checked")
        records = []

    record_errors, record_warnings, duplicate_count = validate_document_records(records)
    errors.extend(record_errors)
    warnings.extend(record_warnings)

    development_records = validate_json_manifest(DEVELOPMENT_JUDGMENTS_MANIFEST, errors)
    if DEVELOPMENT_JUDGMENTS_MANIFEST.exists():
        dev_errors, dev_warnings, dev_duplicate_count = validate_development_judgments(
            development_records
        )
        errors.extend(dev_errors)
        warnings.extend(dev_warnings)
        duplicate_count += dev_duplicate_count

    print(f"Documents checked: {len(records) + len(development_records)}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Duplicates: {duplicate_count}")

    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
