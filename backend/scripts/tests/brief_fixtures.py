"""Load the professional-brief fixtures (fixtures/briefs/) as real PDFs and private chunks.

Each fixture's text is rendered into a PDF with PyMuPDF (one page per part; a
line containing only ``\\f`` separates pages), then parsed, chunked and wrapped
exactly as an uploaded professional PDF is: ``parse_document`` ->
``chunk_document`` -> ``build_private_chunks``.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pymupdf

from backend.app.services.chunker import chunk_document
from backend.app.services.document_parser import parse_document
from backend.app.services.private_pdf_rag import PrivateChunk, build_private_chunks

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "briefs"
FIXTURE_NAMES = ("judgment", "fir", "chargesheet", "petition", "unknown")
PAGE_BREAK = "\\f"


def expected(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.expected.json").read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / expected(name)["fixture"]).read_text(encoding="utf-8")


def fixture_pages(name: str) -> list[str]:
    pages, current = [], []
    for line in fixture_text(name).splitlines():
        if line.strip() == PAGE_BREAK:
            pages.append("\n".join(current))
            current = []
        else:
            current.append(line)
    pages.append("\n".join(current))
    return [page for page in pages if page.strip()]


def write_fixture_pdf(name: str, directory: Path) -> Path:
    path = directory / expected(name)["fixture"].replace(".txt", ".pdf")
    document = pymupdf.open()
    for page_text in fixture_pages(name):
        page = document.new_page(width=595, height=842)  # A4
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), page_text, fontsize=9, fontname="helv")
    document.save(path)
    document.close()
    return path


def fixture_pdf_bytes(name: str) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        return write_fixture_pdf(name, Path(directory)).read_bytes()


def fixture_private_chunks(name: str) -> tuple[str, list[PrivateChunk]]:
    """(filename, private chunks) for a fixture, through the product parser and chunker."""
    with tempfile.TemporaryDirectory() as directory:
        path = write_fixture_pdf(name, Path(directory))
        document = parse_document(path)
        document["source_file_name"] = path.name
        return path.name, build_private_chunks(chunk_document(document))
