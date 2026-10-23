"""OCR fallback in the shared document parser (RAG-005). No database, no network, no LLM.

Tests that run Tesseract are skipped, with the reason, when it is not installed.
The acceptance run must have it (see docs/OCR.md).
"""

from __future__ import annotations

import asyncio
import re
import statistics
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
import pymupdf

from backend.app.core.config import Settings
from backend.app.services import ocr as ocr_service
from backend.app.services.chunker import chunk_document
from backend.app.services.document_parser import DocumentParsingError, OcrLimitExceeded, OcrUnavailable, parse_document
from backend.scripts.tests.brief_fixtures import write_fixture_pdf
from backend.scripts.tests.ocr_fixtures import OCR_FIXTURE_DIR, OVER_CAP_PAGES, ground_truth_pages

TESSERACT = ocr_service.tesseract_status(Settings())
REQUIRES_TESSERACT = unittest.skipUnless(
    TESSERACT.get("available"), f"Tesseract OCR is not available: {TESSERACT.get('reason')}. Install it (docs/OCR.md) to run these tests."
)
CLEAN_SCAN_MIN_ACCURACY = 0.95


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def char_accuracy(reference: str, hypothesis: str) -> float:
    """1 - Levenshtein distance / reference length, on whitespace-collapsed text."""
    a, b = flat(reference), flat(hypothesis)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
        previous = current
    return 1 - previous[-1] / max(1, len(a))


def settings(**overrides) -> Settings:
    return Settings(**overrides)


@REQUIRES_TESSERACT
class OcrAccuracyTests(unittest.TestCase):
    """Character accuracy of OCR text against the source text of each page."""

    CASES = {
        "fir_scanned.pdf": [(1, "fir", 0), (2, "fir", 1)],
        "judgment_page_scanned.pdf": [(1, "judgment", 0)],
        "mixed_text_and_scanned.pdf": [(2, "fir", 0), (4, "judgment", 0)],
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.truth = {name: ground_truth_pages(name) for name in ("fir", "judgment", "petition", "chargesheet")}
        cls.parsed = {fixture: parse_document(OCR_FIXTURE_DIR / fixture, ocr_profile="query") for fixture in (*cls.CASES, "fir_degraded_scan.pdf")}

    def test_clean_scans_meet_the_accuracy_threshold(self) -> None:
        rows, seconds = [], []
        for fixture, pages in self.CASES.items():
            document = self.parsed[fixture]
            text_by_page = {page["page_number"]: page["text"] for page in document["pages"]}
            seconds += list(document["extraction"]["ocr_seconds"].values())
            for number, source, index in pages:
                accuracy = char_accuracy(self.truth[source][index], text_by_page[number])
                rows.append((fixture, number, round(accuracy, 4), document["extraction"]["ocr_page_confidence"][str(number)]))
                with self.subTest(fixture=fixture, page=number):
                    self.assertEqual(document["extraction"]["page_methods"][str(number)], "ocr")
                    self.assertGreaterEqual(accuracy, CLEAN_SCAN_MIN_ACCURACY)
        degraded = self.parsed["fir_degraded_scan.pdf"]
        rows.append(("fir_degraded_scan.pdf", 1, round(char_accuracy(self.truth["fir"][0], degraded["pages"][0]["text"]), 4),
                     degraded["extraction"]["ocr_page_confidence"]["1"]))
        seconds += list(degraded["extraction"]["ocr_seconds"].values())
        print("\nOCR ACCURACY (fixture, page, char accuracy, mean confidence):", rows)
        print(f"OCR SECONDS PER PAGE p50={statistics.median(seconds):.3f} max={max(seconds):.3f} n={len(seconds)}")

    def test_ocr_pages_are_recorded_with_confidence(self) -> None:
        extraction = self.parsed["fir_scanned.pdf"]["extraction"]
        self.assertTrue(extraction["ocr_attempted"])
        self.assertEqual((extraction["document_method"], extraction["method"]), ("ocr", "tesseract_ocr"))
        self.assertEqual(extraction["ocr_pages"], [1, 2])
        self.assertEqual(extraction["page_methods"], {"1": "ocr", "2": "ocr"})
        self.assertTrue(all(value >= 80 for value in extraction["ocr_page_confidence"].values()))
        self.assertGreaterEqual(extraction["ocr_mean_confidence"], 80)
        self.assertFalse(extraction["ocr_low_confidence"])
        self.assertIn("tesseract", extraction["ocr_engine"])


@REQUIRES_TESSERACT
class MixedDocumentTests(unittest.TestCase):
    def test_only_scanned_pages_are_ocred_and_provenance_is_kept(self) -> None:
        document = parse_document(OCR_FIXTURE_DIR / "mixed_text_and_scanned.pdf", ocr_profile="query")
        extraction = document["extraction"]
        self.assertEqual((extraction["document_method"], extraction["method"]), ("mixed", "pymupdf_native_text+tesseract_ocr"))
        self.assertEqual(extraction["ocr_pages"], [2, 4])
        self.assertEqual(extraction["page_methods"], {"1": "native", "2": "ocr", "3": "native", "4": "ocr"})
        self.assertEqual(sorted(extraction["ocr_page_confidence"]), ["2", "4"])
        self.assertEqual([page["page_number"] for page in document["pages"]], [1, 2, 3, 4])
        # Native pages are byte-identical to the text path.
        self.assertEqual(document["pages"][0]["text"], ground_truth_pages("petition")[0])
        self.assertEqual(document["pages"][2]["text"], ground_truth_pages("chargesheet")[0])
        # Paragraphs and chunks carry the page they came from.
        self.assertTrue({paragraph["page_start"] for paragraph in document["paragraphs"]} == {1, 2, 3, 4})
        fir_markers = [paragraph for paragraph in document["paragraphs"] if "Meera Placeholder" in paragraph["text"]]
        self.assertTrue(fir_markers and all(paragraph["page_start"] == 2 for paragraph in fir_markers))
        chunks = chunk_document(document)
        self.assertTrue(all(1 <= chunk["page_start"] <= chunk["page_end"] <= 4 for chunk in chunks))


@REQUIRES_TESSERACT
class QualityAndLimitTests(unittest.TestCase):
    def test_degraded_scan_is_flagged_low_confidence(self) -> None:
        extraction = parse_document(OCR_FIXTURE_DIR / "fir_degraded_scan.pdf", ocr_profile="query")["extraction"]
        self.assertEqual(extraction["ocr_pages"], [1])
        self.assertLess(extraction["ocr_page_confidence"]["1"], Settings().ocr_low_confidence_threshold)
        self.assertTrue(extraction["ocr_low_confidence"])

    def test_page_cap_is_enforced_before_any_ocr_runs(self) -> None:
        with patch.object(ocr_service, "ocr_page", side_effect=AssertionError("OCR must not run")):
            with self.assertRaises(OcrLimitExceeded) as raised:
                parse_document(OCR_FIXTURE_DIR / "over_cap_scanned.pdf", ocr_profile="query")
        self.assertEqual(raised.exception.code, "OCR_LIMIT_EXCEEDED")
        self.assertIn(f"{OVER_CAP_PAGES} scanned pages exceed the OCR limit of 10", str(raised.exception))

    def test_ingestion_profile_has_a_larger_cap(self) -> None:
        document = parse_document(OCR_FIXTURE_DIR / "over_cap_scanned.pdf", ocr_profile="ingestion", settings=settings(ocr_dpi=150))
        self.assertEqual(len(document["extraction"]["ocr_pages"]), OVER_CAP_PAGES)

    def test_page_and_document_timeouts_fail_cleanly(self) -> None:
        with patch.object(ocr_service, "ocr_page", side_effect=ocr_service.OcrPageTimeout("Tesseract page timeout")):
            with self.assertRaisesRegex(OcrLimitExceeded, "page time limit"):
                parse_document(OCR_FIXTURE_DIR / "fir_scanned.pdf", ocr_profile="query")
        with self.assertRaisesRegex(OcrLimitExceeded, "document time limit"):
            parse_document(OCR_FIXTURE_DIR / "fir_scanned.pdf", ocr_profile="query", settings=settings(ocr_document_timeout_seconds_query=0))

    def test_pytesseract_timeout_error_is_mapped_to_a_page_timeout(self) -> None:
        # pytesseract kills Tesseract after `timeout` and raises RuntimeError("Tesseract process timeout").
        page = pymupdf.open(OCR_FIXTURE_DIR / "judgment_page_scanned.pdf")[0]
        with patch("pytesseract.image_to_data", side_effect=RuntimeError("Tesseract process timeout")):
            with self.assertRaises(ocr_service.OcrPageTimeout):
                ocr_service.ocr_page(page, Settings(), timeout_seconds=1)


class MissingTesseractTests(unittest.TestCase):
    """Simulated: a tesseract binary that does not exist."""

    def setUp(self) -> None:
        ocr_service.clear_tesseract_status_cache()
        self.addCleanup(ocr_service.clear_tesseract_status_cache)
        self.missing = settings(tesseract_cmd="/nonexistent/legalai/tesseract")

    def test_status_reports_unavailable_and_scans_fail_with_ocr_unavailable(self) -> None:
        status = ocr_service.tesseract_status(self.missing)
        self.assertFalse(status["available"])
        self.assertIn("not usable", status["reason"])
        with self.assertRaises(OcrUnavailable) as raised:
            parse_document(OCR_FIXTURE_DIR / "fir_scanned.pdf", ocr_profile="query", settings=self.missing)
        self.assertEqual(raised.exception.code, "OCR_UNAVAILABLE")
        self.assertNotIn("/nonexistent", str(raised.exception))

    def test_mixed_document_is_not_returned_partially(self) -> None:
        with self.assertRaises(OcrUnavailable):
            parse_document(OCR_FIXTURE_DIR / "mixed_text_and_scanned.pdf", ocr_profile="query", settings=self.missing)

    def test_text_pdfs_never_need_tesseract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = parse_document(write_fixture_pdf("fir", Path(directory)), ocr_profile="query", settings=self.missing)
        self.assertEqual((document["extraction"]["document_method"], document["extraction"]["method"]), ("native", "pymupdf_native_text"))
        self.assertFalse(document["extraction"]["ocr_attempted"])

    def test_missing_language_data_is_unavailable(self) -> None:
        if not TESSERACT.get("available"):
            self.skipTest(f"Tesseract OCR is not available: {TESSERACT.get('reason')}")
        status = ocr_service.tesseract_status(settings(ocr_language="xxx"))
        self.assertFalse(status["available"])
        self.assertIn("language data missing: xxx", status["reason"])


class NativePathTests(unittest.TestCase):
    """The native-text path is unchanged: text PDFs and blank pages never trigger OCR."""

    def test_text_pdf_and_blank_pages_skip_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture_pdf("judgment", Path(directory))
            document = pymupdf.open(path)
            document.new_page()  # a blank page: short text but no image, so nothing to OCR
            blank_path = Path(directory) / "with_blank.pdf"
            document.save(blank_path)
            with patch.object(ocr_service, "ocr_page", side_effect=AssertionError("OCR must not run")):
                parsed = parse_document(blank_path, ocr_profile="query")
        self.assertEqual((parsed["extraction"]["document_method"], parsed["extraction"]["method"]), ("native", "pymupdf_native_text"))
        self.assertFalse(parsed["extraction"]["ocr_attempted"])
        self.assertEqual(parsed["extraction"]["ocr_pages"], [])

    def test_ocr_disabled_keeps_the_old_no_text_error(self) -> None:
        with self.assertRaisesRegex(DocumentParsingError, "no extractable native text"):
            parse_document(OCR_FIXTURE_DIR / "fir_scanned.pdf", ocr_profile="query", settings=settings(ocr_enabled=False))

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_document(OCR_FIXTURE_DIR / "fir_scanned.pdf", ocr_profile="other")


class HealthOcrStatusTests(unittest.TestCase):
    def test_health_reports_ocr_availability(self) -> None:
        from backend.main import app

        async def call() -> dict:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return (await client.get("/health")).json()

        with patch("backend.main.check_db_connection", return_value=(True, "connected")):
            body = asyncio.run(call())
        self.assertIn("ocr", body)
        self.assertEqual(body["ocr"]["available"], bool(TESSERACT.get("available")))
        if TESSERACT.get("available"):
            self.assertRegex(body["ocr"]["version"], r"^\d+\.\d+")
            self.assertIn("eng", body["ocr"]["languages"])


if __name__ == "__main__":
    unittest.main()
