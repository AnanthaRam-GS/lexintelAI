"""Reusable document parsing service for backend ingestion.

This adapter exposes the existing Phase 0 native-PDF extraction and
normalization behavior through the stable `parse_document(path)` contract used
by the ingestion state machine.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.scripts import process_judgment_corpus as judgment_processing


class DocumentParsingError(RuntimeError):
    """Raised when a document cannot be parsed into usable text."""


def parse_document(path: str | Path) -> dict[str, Any]:
    """Parse a local PDF into normalized text, page records, and paragraphs.

    Args:
        path: Local filesystem path to a PDF file.

    Returns:
        A structured dictionary consumed by `chunk_document`.

    Raises:
        DocumentParsingError: If the path is missing, unreadable, non-PDF, or
            contains no extractable native text.
    """
    source_path = Path(path)
    if not source_path.exists():
        raise DocumentParsingError("Document file does not exist.")
    if not source_path.is_file():
        raise DocumentParsingError("Document path is not a file.")
    if source_path.suffix.lower() != ".pdf":
        raise DocumentParsingError("Only PDF documents are supported by this adapter.")

    checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
    document_id = f"local:{checksum[:16]}"
    entry = _entry_for(source_path, checksum, document_id)
    loaded = judgment_processing.load_pdf(entry, source_path)
    if loaded.warnings and any(warning.startswith("pdf_extract_failed") for warning in loaded.warnings):
        raise DocumentParsingError("PDF text extraction failed.")

    pages = loaded.pages
    text = judgment_processing.normalize_text("\n\n".join(page.get("text", "") for page in pages))
    if not text:
        raise DocumentParsingError("PDF contains no extractable native text.")

    paragraphs, diagnostics = judgment_processing.paragraph_blocks(entry, loaded)
    if not paragraphs:
        raise DocumentParsingError("PDF contains no parseable text blocks.")

    return {
        "document_id": document_id,
        "source_file_path": str(source_path),
        "source_file_name": source_path.name,
        "sha256": checksum,
        "text": text,
        "page_count": len(pages),
        "pages": pages,
        "paragraphs": paragraphs,
        "metadata": {
            "provider": "local_upload",
            "source_document_id": checksum[:16],
            "raw_path": str(source_path),
            "raw_mime_type": "application/pdf",
            "text_source_type": loaded.text_source_type,
            "normalizer_version": judgment_processing.NORMALIZER_VERSION,
        },
        "extraction": {
            "method": "pymupdf_native_text",
            "ocr_attempted": False,
            "ocr_used": False,
            "warnings": loaded.warnings,
            "header_footer_diagnostics": diagnostics,
        },
    }


def _entry_for(source_path: Path, checksum: str, document_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "provider": "local_upload",
        "source_document_id": checksum[:16],
        "source_url": None,
        "case_title": source_path.stem,
        "court": None,
        "decision_date": None,
        "decision_year": None,
        "effective_offence_family": None,
        "effective_legal_regime": None,
        "raw_path": str(source_path),
        "raw_mime_type": "application/pdf",
        "sha256": checksum,
        "text_source_type": "pdf_native",
        "human_review_source": None,
        "human_review_status": None,
        "automated": {},
        "attribution_text": None,
    }
