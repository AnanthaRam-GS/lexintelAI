# OCR Fallback For Scanned PDFs (RAG-005, R07)

Flow 1: if a page's extracted text is empty or below a threshold, Tesseract OCR is applied. This covers query-time
uploads (`/query/public/pdf`, `/query/professional/pdf`) and admin ingestion (`/ingest/upload`). The corpus
processing pipeline (`process_judgment_corpus.py`), chunking parameters, Chroma and BM25 are unchanged.

## System dependency

OCR needs the Tesseract binary as well as the Python package.

| Component | Version tested | Install |
|---|---|---|
| Tesseract | 5.5.3 (leptonica 1.87.0) | macOS: `brew install tesseract` |
| English language data (`eng`) | bundled with the Homebrew formula | included |
| Other languages (optional) | — | macOS: `brew install tesseract-lang` (all languages); then set `OCR_LANGUAGE`, for example `eng+hin` |
| `pytesseract` | 0.3.13 (pinned in `requirements.txt`) | `pip install -r requirements.txt` |
| `pillow` | 13.0.0 (pinned; needed by pytesseract) | same |

On Debian or Ubuntu, `apt-get install tesseract-ocr` plus `tesseract-ocr-<lang>` packages give the same result.

Check the install with `tesseract --version` and `tesseract --list-langs`. `GET /health` reports the result as
`ocr: {enabled, available, version, languages, language}`, or `ocr: {available: false, reason}` when the binary,
`pytesseract` or the configured language data is missing. If Tesseract is not on `PATH`, set `TESSERACT_CMD` to its
full path.

Without Tesseract, text PDFs work exactly as before. Only scanned pages fail, with `OCR_UNAVAILABLE`.

## How pages are chosen

For each page of a PDF (`services/document_parser.py`):

1. PyMuPDF extracts the native text, as before.
2. The page is OCR'd only if its native text is shorter than `OCR_MIN_CHARS_PER_PAGE` (default 50) **and** it contains
   an image. A blank page has nothing to read and is never OCR'd, so blank pages in text PDFs cost nothing and never
   count towards the page cap.
3. The page is rendered at `OCR_DPI` (default 300) in grayscale, and Tesseract runs once (`image_to_data`, language
   `OCR_LANGUAGE`, default `eng`). The text is rebuilt from Tesseract's block, paragraph and line structure, so a
   blank line separates paragraphs as in native text.
4. The OCR text goes through the same cleaning and normalization as native text (`normalize_pdf_text`, then
   `normalize_text`). It keeps its page number, so paragraphs, chunks, `page_start` / `page_end` and `P#` provenance
   work identically.
5. OCR text replaces the native text only if it is longer; otherwise the page stays `native`.

Text pages in a mixed PDF are never OCR'd and their text is byte-identical to the text-only path.

## Provenance recorded

`parse_document(...)["extraction"]` includes the following keys:
- `document_method`: `native`, `ocr` (every page OCR'd) or `mixed`;
- `method`: unchanged `pymupdf_native_text` for text PDFs, otherwise `tesseract_ocr` or
  `pymupdf_native_text+tesseract_ocr`;
- `ocr_attempted`, `ocr_used`;
- `ocr_pages`: the page numbers whose text came from OCR;
- `page_methods`: `{page: "native" | "ocr"}`;
- `ocr_page_confidence`: `{page: mean Tesseract word confidence, 0-100}`;
- `ocr_mean_confidence`: word-weighted, over the OCR'd pages;
- `ocr_low_confidence`, `ocr_seconds` and `ocr_engine`.

Admin ingestion stores `documents.extraction_method`, `documents.ocr_pages` and `documents.ocr_mean_confidence`
(migration `0009_document_extraction`). Documents ingested before 0009 have NULL: their method was not recorded.
Chroma and BM25 metadata are unchanged in this step.

## Limits

| Setting | Default | Meaning |
|---|---|---|
| `OCR_ENABLED` | `true` | `false` restores the old behaviour (scans fail with `PDF_NO_TEXT`) |
| `OCR_MIN_CHARS_PER_PAGE` | 50 | pages with less native text (and an image) are OCR'd |
| `OCR_DPI` | 300 | render resolution |
| `OCR_LANGUAGE` | `eng` | Tesseract language(s), for example `eng+hin` |
| `OCR_MAX_PAGES_QUERY` | 10 | pages that may be OCR'd in a query-time upload |
| `OCR_MAX_PAGES_INGESTION` | 200 | pages that may be OCR'd in an admin ingestion |
| `OCR_PAGE_TIMEOUT_SECONDS` | 30 | Tesseract is killed after this per page |
| `OCR_DOCUMENT_TIMEOUT_SECONDS_QUERY` | 90 | total OCR time per query-time upload |
| `OCR_DOCUMENT_TIMEOUT_SECONDS_INGESTION` | 1800 | total OCR time per ingestion |
| `OCR_LOW_CONFIDENCE_THRESHOLD` | 80 | mean confidence below which a page is flagged |
| `TESSERACT_CMD` | empty | full path to `tesseract` if it is not on `PATH` |

- The page cap is checked before any OCR runs.
- Exceeding the cap, the page timeout or the document timeout fails the whole document with `OCR_LIMIT_EXCEEDED`.
  Nothing partial is ever returned.
- OCR runs off the event loop: query uploads parse in the threadpool (BE-004), and ingestion runs as a background
  task.
- On this machine (Apple M5), OCR takes about 0.6 s per page at 300 DPI, so 10 pages take about 6 s.

## Quality signalling

When any OCR'd page has a mean confidence below `OCR_LOW_CONFIDENCE_THRESHOLD`, the response carries this limitation:

> Parts of this document were read by OCR (text recognition from a scan) with low confidence, so names, dates and
> figures taken from it may contain errors. Check them against the original.

- **Professional:** it goes in `case_brief.limitations`.
- **Public:** it goes in the new `limitations` list, which the answer card shows as a note.

Clean scans (confidence about 95) carry no warning.

## Errors

| Code | HTTP (query) | Ingestion `error_code` | When |
|---|---|---|---|
| `OCR_LIMIT_EXCEEDED` | 422 | `OCR_LIMIT_EXCEEDED` | more scanned pages than the cap, or a timeout |
| `OCR_UNAVAILABLE` | 503 | `OCR_UNAVAILABLE` | pages need OCR but Tesseract, `pytesseract` or the language data is missing |
| `PDF_NO_TEXT` | 422 | `PDF_NO_TEXT` | no text even after OCR (or OCR disabled) |

Messages are plain language and never include paths or Tesseract output.

## Measured accuracy (step 14 fixtures, Tesseract 5.5.3, `eng`, 300 DPI)

Character accuracy is 1 − Levenshtein distance / source length, on whitespace-collapsed text, against the same page's
native text.

| Fixture | Page | Char accuracy | Mean confidence |
|---|---|---:|---:|
| `fir_scanned.pdf` | 1 | 99.81% | 95.2 |
| `fir_scanned.pdf` | 2 | 100.00% | 95.3 |
| `judgment_page_scanned.pdf` | 1 | 99.90% | 95.3 |
| `mixed_text_and_scanned.pdf` | 2 (scan) | 99.81% | 95.2 |
| `mixed_text_and_scanned.pdf` | 4 (scan) | 99.90% | 95.3 |
| `fir_degraded_scan.pdf` | 1 | 72.58% | 67.3 (flagged) |

- The clean-scan threshold in the tests is ≥ 95%.
- The remaining errors are single-glyph confusions (`I`→`|`, `H`→`h`, `I`→`l`). None touches a party, date, stage or
  evidence term, so the scanned FIR brief matches `fir.expected.json` with no tolerance needed.
- OCR time was 0.57 s per page at p50 (max 0.79 s, n = 6).

Fixtures and their provenance are described in `backend/scripts/tests/fixtures/ocr/README.md`. Tests:
`test_ocr_parser.py` (no database) and `test_ocr_pipeline.py` (DB suite). Both skip, with the reason, when Tesseract is
missing.
