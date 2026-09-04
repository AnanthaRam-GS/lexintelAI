"""Deterministic native-PDF text extraction for human review previews."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class PdfTextExtraction:
    page_count: int
    text: str
    text_length: int
    pages_with_text: int
    pages_without_text: int
    extraction_status: str
    error: str | None = None


def normalize_pdf_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


def status_for_text(text: str, page_count: int, pages_with_text: int) -> str:
    if page_count == 0 or pages_with_text == 0 or not text:
        return "empty"
    if len(text) < 500:
        return "sparse"
    return "usable"


def extract_pdf_text(path: Path) -> PdfTextExtraction:
    try:
        import pymupdf
    except ImportError as exc:
        return PdfTextExtraction(
            page_count=0,
            text="",
            text_length=0,
            pages_with_text=0,
            pages_without_text=0,
            extraction_status="failed",
            error=f"PyMuPDF is not installed: {exc}",
        )

    try:
        with pymupdf.open(path) as document:
            page_texts: list[str] = []
            pages_with_text = 0
            for page in document:
                text = normalize_pdf_text(page.get_text("text"))
                if text:
                    pages_with_text += 1
                page_texts.append(text)
            combined = normalize_pdf_text("\n\n".join(page_texts))
            page_count = document.page_count
            return PdfTextExtraction(
                page_count=page_count,
                text=combined,
                text_length=len(combined),
                pages_with_text=pages_with_text,
                pages_without_text=page_count - pages_with_text,
                extraction_status=status_for_text(combined, page_count, pages_with_text),
            )
    except Exception as exc:
        return PdfTextExtraction(
            page_count=0,
            text="",
            text_length=0,
            pages_with_text=0,
            pages_without_text=0,
            extraction_status="failed",
            error=str(exc),
        )
