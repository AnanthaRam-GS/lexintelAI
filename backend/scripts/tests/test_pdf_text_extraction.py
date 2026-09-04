"""Tests for deterministic native-PDF text extraction."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pymupdf

from backend.scripts import generate_judgment_review_report as report
from backend.scripts.pdf_text_extraction import extract_pdf_text, normalize_pdf_text
from backend.scripts.corpus_utils import sha256_file


def write_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


class PdfTextExtractionTest(unittest.TestCase):
    def test_extracts_normal_text_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.pdf"
            write_pdf(path, ["Example High Court\nA v State\nSection 302 IPC"])

            extracted = extract_pdf_text(path)

        self.assertEqual(extracted.extraction_status, "sparse")
        self.assertIn("Example High Court", extracted.text)
        self.assertEqual(extracted.page_count, 1)
        self.assertEqual(extracted.pages_with_text, 1)
        self.assertEqual(extracted.pages_without_text, 0)

    def test_preserves_multi_page_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "multi.pdf"
            write_pdf(path, ["First page heading", "Second page facts"])

            extracted = extract_pdf_text(path)

        self.assertLess(extracted.text.index("First page heading"), extracted.text.index("Second page facts"))
        self.assertEqual(extracted.page_count, 2)
        self.assertEqual(extracted.pages_with_text, 2)

    def test_empty_textless_pdf_is_marked_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "empty.pdf"
            write_pdf(path, [""])

            extracted = extract_pdf_text(path)

        self.assertEqual(extracted.extraction_status, "empty")
        self.assertEqual(extracted.text, "")
        self.assertEqual(extracted.pages_with_text, 0)
        self.assertEqual(extracted.pages_without_text, 1)

    def test_corrupt_pdf_is_marked_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "corrupt.pdf"
            path.write_bytes(b"not a pdf")

            extracted = extract_pdf_text(path)

        self.assertEqual(extracted.extraction_status, "failed")
        self.assertEqual(extracted.text, "")
        self.assertIsNotNone(extracted.error)

    def test_whitespace_normalization(self) -> None:
        self.assertEqual(normalize_pdf_text(" A\t\tB\n\n\n C  "), "A B\n\nC")

    def test_preview_is_bounded_and_reports_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = root / "long.pdf"
            write_pdf(path, ["A v State " * 600])
            record = {
                "raw_file_path": "long.pdf",
                "mime_type": "application/pdf",
            }

            preview, available, provenance = report.preview_for(record, repo_root=root)

        self.assertTrue(available)
        self.assertLessEqual(len(preview), report.PDF_PREVIEW_LIMIT)
        self.assertIn("* Preview source: PDF native text", provenance)
        self.assertIn("* PDF pages: 1", provenance)

    def test_original_pdf_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.pdf"
            write_pdf(path, ["A v State"])
            before = sha256_file(path)

            extract_pdf_text(path)

            self.assertEqual(sha256_file(path), before)


if __name__ == "__main__":
    unittest.main()
