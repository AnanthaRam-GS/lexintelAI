# OCR fixtures (RAG-005)

Image-only (scanned) PDFs for the OCR fallback tests. None has a native text
layer on its scanned pages. They are generated, deterministically, by
`backend/scripts/tests/ocr_fixtures.py` from the professional-brief fixtures in
`../briefs/`, so they contain **no real personal data**: the FIR, charge sheet
and petition are the SYNTHETIC documents described in `../briefs/README.md`,
and the judgment page is the public Indian Kanoon excerpt already used there.

| File | Pages | Made from | Used for |
|---|---|---|---|
| `fir_scanned.pdf` | 2 scanned | synthetic FIR, rasterized at 200 DPI | accuracy; scanned-FIR brief vs `../briefs/fir.expected.json` |
| `judgment_page_scanned.pdf` | 1 scanned | page 1 of the public judgment excerpt, 200 DPI | accuracy; ingestion rehearsal |
| `mixed_text_and_scanned.pdf` | 4: text, scan, text, scan | petition p1 (text), FIR p1 (scan), charge sheet p1 (text), judgment p1 (scan) | OCR only on pages 2 and 4; page provenance |
| `fir_degraded_scan.pdf` | 1 scanned | FIR p1 at 150 DPI, rotated 1.5 degrees, blurred, seeded noise, JPEG quality 35 | low-confidence limitation |
| `over_cap_scanned.pdf` | 12 scanned | a one-line synthetic page, tiny images | query-time cap of 10 (`OCR_LIMIT_EXCEEDED`) |

Regenerate after changing the brief fixtures:

```
.venv/bin/python -m backend.scripts.tests.ocr_fixtures
```

Ground truth for accuracy is the native text of the same page rendered as a
text PDF and parsed by the product parser (`ocr_fixtures.ground_truth_pages`).
