"""Reusable document parsing service for backend ingestion and query uploads.

This adapter exposes the existing Phase 0 native-PDF extraction and
normalization behavior through the stable `parse_document(path)` contract used
by the ingestion state machine and the query-time PDF routes.

OCR fallback (RAG-005): a page whose native text is shorter than
OCR_MIN_CHARS_PER_PAGE and which contains an image is rendered and read with
Tesseract (services/ocr.py). OCR text goes through the same cleaning and
normalization as native text and keeps the page number, so paragraphs, chunks
and P# provenance work identically. Limits: at most OCR_MAX_PAGES_QUERY /
OCR_MAX_PAGES_INGESTION pages, a per-page and a per-document timeout. Over a
limit, or without a usable Tesseract, parsing fails with OcrLimitExceeded or
OcrUnavailable rather than returning a partial document.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import statistics
import time
from typing import Any

from backend.app.core.config import Settings
from backend.scripts import process_judgment_corpus as judgment_processing
from backend.scripts.pdf_text_extraction import normalize_pdf_text

logger = logging.getLogger("legalai.document_parser")

OCR_PROFILES = ("query", "ingestion")
EXTRACTION_METHODS = {
    "native": "pymupdf_native_text",
    "ocr": "tesseract_ocr",
    "mixed": "pymupdf_native_text+tesseract_ocr",
}


class DocumentParsingError(RuntimeError):
    """Raised when a document cannot be parsed into usable text."""

    code = "PARSE_FAILED"


class OcrLimitExceeded(DocumentParsingError):
    """The scanned pages exceed the OCR page cap or time budget; nothing partial is returned."""

    code = "OCR_LIMIT_EXCEEDED"


class OcrUnavailable(DocumentParsingError):
    """Scanned pages need OCR, but Tesseract (or its language data) is not usable."""

    code = "OCR_UNAVAILABLE"


def ocr_limits(settings: Settings, profile: str) -> tuple[int, float]:
    """(max pages, document timeout seconds) for a query-time upload or an admin ingestion."""
    if profile == "query":
        return settings.ocr_max_pages_query, settings.ocr_document_timeout_seconds_query
    return settings.ocr_max_pages_ingestion, settings.ocr_document_timeout_seconds_ingestion


def parse_document(path: str | Path, *, ocr_profile: str = "ingestion", settings: Settings | None = None) -> dict[str, Any]:
    """Parse a local PDF into normalized text, page records, and paragraphs.

    Args:
        path: Local filesystem path to a PDF file.

    Returns:
        A structured dictionary consumed by `chunk_document`.

    Raises:
        DocumentParsingError: If the path is missing, unreadable, non-PDF, or
            contains no extractable text (native or OCR).
        OcrLimitExceeded: Too many pages need OCR, or OCR ran out of time.
        OcrUnavailable: Pages need OCR but Tesseract is not usable.
    """
    if ocr_profile not in OCR_PROFILES:
        raise ValueError(f"unknown OCR profile: {ocr_profile}")
    settings = settings or Settings()
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

    loaded, ocr = apply_ocr_fallback(source_path, loaded, settings=settings, profile=ocr_profile)
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
            # Unchanged for text PDFs; scanned pages add Tesseract. document_method is the short form (native | ocr | mixed).
            "method": EXTRACTION_METHODS[ocr["document_method"]],
            "document_method": ocr["document_method"],
            "ocr_attempted": ocr["ocr_attempted"],
            "ocr_used": bool(ocr["ocr_pages"]),
            "ocr_pages": ocr["ocr_pages"],
            "page_methods": ocr["page_methods"],
            "ocr_page_confidence": ocr["ocr_page_confidence"],
            "ocr_mean_confidence": ocr["ocr_mean_confidence"],
            "ocr_low_confidence": ocr["ocr_low_confidence"],
            "ocr_seconds": ocr["ocr_seconds"],
            "ocr_engine": ocr["ocr_engine"],
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


def _ocr_candidates(source_path: Path, pages: list[dict[str, Any]], min_chars: int) -> list[int]:
    """Page numbers whose native text is short and which carry an image (a scan); blank pages are skipped."""
    import pymupdf

    short = {page["page_number"] for page in pages if page.get("page_number") and len(page.get("text", "").strip()) < min_chars}
    if not short:
        return []
    with pymupdf.open(source_path) as document:
        return [number for number in sorted(short) if document[number - 1].get_images(full=True)]


def apply_ocr_fallback(
    source_path: Path, loaded: Any, *, settings: Settings, profile: str
) -> tuple[Any, dict[str, Any]]:
    """Replace short scanned pages with OCR text; returns (loaded, OCR provenance)."""
    page_methods = {str(page["page_number"]): "native" for page in loaded.pages if page.get("page_number")}
    summary: dict[str, Any] = {
        "document_method": "native",
        "ocr_attempted": False,
        "ocr_pages": [],
        "page_methods": page_methods,
        "ocr_page_confidence": {},
        "ocr_mean_confidence": None,
        "ocr_low_confidence": False,
        "ocr_seconds": {},
        "ocr_engine": None,
    }
    if not settings.ocr_enabled or not loaded.pages:
        return loaded, summary
    candidates = _ocr_candidates(source_path, loaded.pages, settings.ocr_min_chars_per_page)
    if not candidates:
        return loaded, summary

    from backend.app.services.ocr import OcrEngineUnavailable, OcrPageTimeout, ocr_page, tesseract_status

    max_pages, document_timeout = ocr_limits(settings, profile)
    if len(candidates) > max_pages:
        raise OcrLimitExceeded(f"{len(candidates)} scanned pages exceed the OCR limit of {max_pages}.")
    status = tesseract_status(settings)
    if not status.get("available"):
        logger.warning("ocr_unavailable reason=%s", status.get("reason"))
        raise OcrUnavailable("Scanned pages need OCR, but OCR is not available.")

    import pymupdf

    summary.update(ocr_attempted=True, ocr_engine=f"tesseract {status.get('version')} ({settings.ocr_language})")
    deadline = time.monotonic() + document_timeout
    by_number = {page["page_number"]: dict(page) for page in loaded.pages}
    weighted: list[tuple[float, int]] = []
    with pymupdf.open(source_path) as document:
        for number in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OcrLimitExceeded("OCR exceeded the document time limit.")
            try:
                result = ocr_page(document[number - 1], settings, timeout_seconds=min(settings.ocr_page_timeout_seconds, remaining))
            except OcrPageTimeout as exc:
                raise OcrLimitExceeded("OCR exceeded the page time limit.") from exc
            except OcrEngineUnavailable as exc:
                logger.warning("ocr_unavailable reason=%s", exc)
                raise OcrUnavailable("Scanned pages need OCR, but OCR is not available.") from exc
            # The same cleaning and normalization as the native-text path (load_pdf).
            text = judgment_processing.normalize_text(normalize_pdf_text(result.text))
            summary["ocr_page_confidence"][str(number)] = result.mean_confidence
            summary["ocr_seconds"][str(number)] = result.seconds
            native = by_number[number].get("text", "")
            if len(text) > len(native.strip()):
                by_number[number]["text"] = text
                page_methods[str(number)] = "ocr"
                summary["ocr_pages"].append(number)
                if result.mean_confidence is not None and result.word_count:
                    weighted.append((result.mean_confidence, result.word_count))
    if weighted:
        total = sum(count for _confidence, count in weighted)
        summary["ocr_mean_confidence"] = round(sum(confidence * count for confidence, count in weighted) / total, 1)
        used = [summary["ocr_page_confidence"][str(number)] for number in summary["ocr_pages"]]
        summary["ocr_low_confidence"] = any(value is None or value < settings.ocr_low_confidence_threshold for value in used)
    if summary["ocr_pages"]:
        summary["document_method"] = "ocr" if len(summary["ocr_pages"]) == len(page_methods) else "mixed"
    logger.info(
        "ocr_fallback profile=%s pages=%s used=%s mean_confidence=%s p50_seconds=%s",
        profile,
        candidates,
        summary["ocr_pages"],
        summary["ocr_mean_confidence"],
        statistics.median(summary["ocr_seconds"].values()) if summary["ocr_seconds"] else None,
    )
    pages = [by_number[page["page_number"]] if page.get("page_number") in by_number else page for page in loaded.pages]
    warnings = [warning for warning in loaded.warnings if not (warning == "pdf_no_native_text" and summary["ocr_pages"])]
    return type(loaded)(loaded.document_id, loaded.text_source_type, loaded.raw_path, pages, warnings), summary
