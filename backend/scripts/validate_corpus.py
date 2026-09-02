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
                if file_obj.read(4) != b"%PDF":
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

    print(f"Documents checked: {len(records)}")
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
