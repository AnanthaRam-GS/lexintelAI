"""Tests for corpus validation helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scripts import validate_corpus


class ValidateCorpusTest(unittest.TestCase):
    def test_valid_pdf_record_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = root / "data/raw/statutes/ipc/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF sample")
            digest = validate_corpus.sha256_file(pdf_path)
            records = [
                {
                    "document_id": "ipc-1860",
                    "document_type": "statute",
                    "title": "Indian Penal Code, 1860",
                    "source_provider": "india_code",
                    "source_url": "https://www.indiacode.nic.in/example.pdf",
                    "source_retrieved_at": "2026-01-01T00:00:00+00:00",
                    "attribution_required": False,
                    "raw_file_path": "data/raw/statutes/ipc/sample.pdf",
                    "sha256": digest,
                    "file_size_bytes": pdf_path.stat().st_size,
                    "mime_type": "application/pdf",
                    "source_document_id": "ipc-1860",
                }
            ]

            with patch.object(validate_corpus, "REPO_ROOT", root):
                errors, warnings, duplicates = validate_corpus.validate_document_records(records)

            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])
            self.assertEqual(duplicates, 0)

    def test_missing_attribution_text_is_error(self) -> None:
        records = [
            {
                "document_id": "doc-1",
                "document_type": "judgment",
                "title": "Sample",
                "source_provider": "indian_kanoon",
                "source_url": "https://api.indiankanoon.org/doc/1/",
                "source_retrieved_at": "2026-01-01T00:00:00+00:00",
                "attribution_required": True,
                "raw_file_path": "missing.pdf",
                "sha256": "abc",
                "file_size_bytes": 1,
                "mime_type": "application/pdf",
            }
        ]

        errors, _warnings, _duplicates = validate_corpus.validate_document_records(records)

        self.assertTrue(any("attribution_text is missing" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
