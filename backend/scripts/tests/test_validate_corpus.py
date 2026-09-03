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

    def test_development_judgment_requires_valid_metadata(self) -> None:
        records = [
            {
                "local_id": "dev-1",
                "source_provider": "indian_kanoon",
                "source_document_id": "1",
                "source_url": "https://indiankanoon.org/doc/1/",
                "case_name": "A v State",
                "court_level": "not_a_court",
                "year": 1700,
                "offence_family": "homicide",
                "raw_file_path": None,
                "sha256": None,
                "file_size_bytes": None,
                "mime_type": None,
                "attribution_required": False,
                "status": "validated",
            }
        ]

        errors, _warnings, _duplicates = validate_corpus.validate_development_judgments(records)

        self.assertTrue(any("invalid court_level" in error for error in errors))
        self.assertTrue(any("invalid year" in error for error in errors))
        self.assertTrue(any("must require attribution" in error for error in errors))
        self.assertTrue(any("validated record missing raw_file_path" in error for error in errors))

    def test_quality_analysis_validates_decisions_regimes_and_scores(self) -> None:
        records = [
            {
                "source_document_id": "1",
                "automated_candidate_decision": "made_up",
                "detected_regime": "ipc_crpc",
                "document_type_score": 1.2,
                "criminal_relevance_score": 0.5,
                "metadata_quality_score": 0.5,
            },
            {
                "source_document_id": "2",
                "automated_candidate_decision": "reject",
                "detected_regime": "made_up",
                "document_type_score": 0.2,
                "criminal_relevance_score": 0.2,
                "metadata_quality_score": 0.2,
            },
        ]

        errors, warnings = validate_corpus.validate_quality_analysis(records, "v1_quality")

        self.assertTrue(any("invalid automated decision" in error for error in errors))
        self.assertTrue(any("invalid score range" in error for error in errors))
        self.assertTrue(any("invalid legal regime" in error for error in errors))
        self.assertEqual(warnings, [])

    def test_v2_audit_validates_temporal_track_and_rejection_reasons(self) -> None:
        records = [
            {
                "source_document_id": "1",
                "final_automated_decision": "reject",
                "detected_regime": "unknown",
                "temporal_track": "future_track",
                "document_type_score": 0.2,
                "criminal_relevance_score": 0.2,
                "metadata_quality_score": 0.2,
                "rejection_reasons": [],
            }
        ]

        errors, warnings = validate_corpus.validate_quality_analysis(records, "v2_audit")

        self.assertTrue(any("invalid temporal_track" in error for error in errors))
        self.assertTrue(any("missing rejection reasons" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
