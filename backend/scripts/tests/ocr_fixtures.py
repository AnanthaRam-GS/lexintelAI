"""Scanned-PDF fixtures for the OCR fallback (fixtures/ocr/), built from the brief fixtures.

Every fixture is rendered from fixtures/briefs/ (synthetic documents, plus one
public judgment excerpt) and rasterized into image-only pages, so it carries
no native text layer. Ground truth for accuracy is the native text of the same
page rendered as a text PDF, through the product parser.

Regenerate the committed PDFs with:
    .venv/bin/python -m backend.scripts.tests.ocr_fixtures
"""

from __future__ import annotations

import io
from pathlib import Path
import random
import tempfile

import pymupdf

from backend.scripts.tests.brief_fixtures import write_fixture_pdf

OCR_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "ocr"
SCAN_DPI = 200
A4 = (595, 842)
OVER_CAP_PAGES = 12  # above the default query-time cap of 10


def _text_pdf(name: str, directory: Path) -> pymupdf.Document:
    return pymupdf.open(write_fixture_pdf(name, directory))


def _png(page: pymupdf.Page, dpi: int) -> bytes:
    return page.get_pixmap(dpi=dpi, colorspace="gray", alpha=False).tobytes("png")


def _degraded(page: pymupdf.Page) -> bytes:
    """Mild blur, seeded noise, a 1.5 degree rotation and JPEG artefacts: a poor but readable scan."""
    from PIL import Image, ImageFilter

    image = Image.open(io.BytesIO(_png(page, 150))).convert("L")
    image = image.rotate(1.5, resample=Image.BICUBIC, expand=False, fillcolor=255)
    image = image.filter(ImageFilter.GaussianBlur(radius=1.1))
    rng = random.Random(20261023)
    pixels = image.load()
    width, height = image.size
    for _ in range(width * height // 25):
        x, y = rng.randrange(width), rng.randrange(height)
        pixels[x, y] = max(0, min(255, pixels[x, y] + rng.choice((-110, -80, 80, 110))))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=35)
    return out.getvalue()


def _add_image_page(document: pymupdf.Document, image: bytes) -> None:
    page = document.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, stream=image)


def _copy_text_page(document: pymupdf.Document, source: pymupdf.Document, index: int) -> None:
    document.insert_pdf(source, from_page=index, to_page=index)


def build_all(target: Path = OCR_FIXTURE_DIR) -> dict[str, Path]:
    target.mkdir(parents=True, exist_ok=True)
    paths = {}
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        fir, judgment, petition, chargesheet = (_text_pdf(name, tmp) for name in ("fir", "judgment", "petition", "chargesheet"))

        scanned_fir = pymupdf.open()
        for page in fir:
            _add_image_page(scanned_fir, _png(page, SCAN_DPI))
        paths["fir_scanned"] = target / "fir_scanned.pdf"

        judgment_page = pymupdf.open()
        _add_image_page(judgment_page, _png(judgment[0], SCAN_DPI))
        paths["judgment_page_scanned"] = target / "judgment_page_scanned.pdf"

        # Pages 1 and 3 keep native text; pages 2 and 4 are scans.
        mixed = pymupdf.open()
        _copy_text_page(mixed, petition, 0)
        _add_image_page(mixed, _png(fir[0], SCAN_DPI))
        _copy_text_page(mixed, chargesheet, 0)
        _add_image_page(mixed, _png(judgment[0], SCAN_DPI))
        paths["mixed"] = target / "mixed_text_and_scanned.pdf"

        degraded = pymupdf.open()
        _add_image_page(degraded, _degraded(fir[0]))
        paths["degraded_scan"] = target / "fir_degraded_scan.pdf"

        # The cap is checked before any OCR runs, so these pages can be tiny images.
        over_cap = pymupdf.open()
        for number in range(1, OVER_CAP_PAGES + 1):
            text_page = pymupdf.open()
            page = text_page.new_page(width=A4[0], height=A4[1])
            page.insert_text((60, 80), f"SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD. Page {number} of {OVER_CAP_PAGES}.", fontsize=14)
            _add_image_page(over_cap, _png(page, 36))
            text_page.close()
        paths["over_cap"] = target / "over_cap_scanned.pdf"

        for key, document in (("fir_scanned", scanned_fir), ("judgment_page_scanned", judgment_page), ("mixed", mixed),
                              ("degraded_scan", degraded), ("over_cap", over_cap)):
            document.set_metadata({"title": f"LegalAI OCR test fixture: {key}", "producer": "legalai ocr_fixtures", "creator": "", "author": ""})
            document.save(paths[key], garbage=4, deflate=True, no_new_id=True)
            document.close()
        for document in (fir, judgment, petition, chargesheet):
            document.close()
    return paths


def ground_truth_pages(name: str) -> list[str]:
    """Native text of each page of brief fixture ``name``, as the product parser extracts it."""
    from backend.app.services.document_parser import parse_document

    with tempfile.TemporaryDirectory() as directory:
        document = parse_document(write_fixture_pdf(name, Path(directory)))
    return [page["text"] for page in document["pages"]]


if __name__ == "__main__":
    for key, path in build_all().items():
        print(f"{key}: {path.relative_to(OCR_FIXTURE_DIR.parents[3])} ({path.stat().st_size // 1024} KiB)")
