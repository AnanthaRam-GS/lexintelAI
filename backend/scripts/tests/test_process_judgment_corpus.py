"""Tests for offline trusted judgment document processing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scripts import process_judgment_corpus as proc


class ProcessJudgmentCorpusTest(unittest.TestCase):
    def test_trusted_selection_counts_and_exclusions(self) -> None:
        manifest = proc.build_trusted_manifest(Path("/tmp/trusted_judgment_processing_manifest_test.json"))
        self.assertEqual(manifest["development_accepted_input"], 28)
        self.assertEqual(manifest["bulk_audit_accepted_input"], 42)
        self.assertEqual(manifest["total_before_dedupe"], 70)
        self.assertEqual(manifest["excluded_policy"]["bulk_rejected"], 7)
        self.assertEqual(manifest["excluded_policy"]["bulk_needs_review"], 1)
        self.assertEqual(manifest["excluded_policy"]["bulk_unaudited"], 199)

    def test_normalization_preserves_paragraphs_and_legal_numbers(self) -> None:
        text = "Para 1\u00ad\ncontinued\n\n2. Section 302 IPC remains.\n\nORDER"
        normalized = proc.normalize_text(text)
        self.assertIn("Para 1 continued", normalized)
        self.assertIn("2. Section 302 IPC", normalized)
        self.assertIn("\n\nORDER", normalized)

    def test_html_text_has_null_page_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "doc.html"
            raw.write_text("<html><body><h1>JUDGMENT</h1><p>1. Criminal appeal text.</p></body></html>", encoding="utf-8")
            entry = self.entry(raw_path="doc.html", mime="text/html", text_source_type="local_text")
            loaded = proc.load_source(entry, root)
            blocks, _ = proc.paragraph_blocks(entry, loaded)
            chunks = proc.chunk_blocks(entry, blocks, target_tokens=20, max_tokens=50, overlap_tokens=5)
            self.assertTrue(chunks)
            self.assertIsNone(chunks[0]["page_start"])
            self.assertIsNone(chunks[0]["page_end"])

    def test_fallback_text_loading_for_provider_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "doc.json"
            raw.write_text('{"errmsg":"Original document not available"}', encoding="utf-8")
            entry = self.entry(raw_path="doc.json", mime="application/json", text_source_type="document_text_fallback")
            entry["regime_evidence"] = ["Fallback Section 379 CrPC judgment text."]
            loaded = proc.load_source(entry, root)
            self.assertEqual(loaded.text_source_type, "document_text_fallback")
            self.assertIn("Section 379", loaded.pages[0]["text"])

    def test_pdf_page_mapping_with_synthetic_loader(self) -> None:
        entry = self.entry(text_source_type="pdf_native")
        loaded = proc.LoadedSource(
            document_id=entry["document_id"],
            text_source_type="pdf_native",
            raw_path="doc.pdf",
            pages=[{"page_number": 1, "text": "JUDGMENT\\n\\n1. First page."}, {"page_number": 2, "text": "2. Second page."}],
            warnings=[],
        )
        blocks, _ = proc.paragraph_blocks(entry, loaded)
        chunks = proc.chunk_blocks(entry, blocks, target_tokens=10, max_tokens=100, overlap_tokens=0)
        self.assertEqual(chunks[0]["page_start"], 1)
        self.assertGreaterEqual(chunks[-1]["page_end"], 1)

    def test_repeated_header_footer_removal_is_conservative(self) -> None:
        pages = [
            {"page_number": 1, "text": "Common Header\n\nBody one\nFooter"},
            {"page_number": 2, "text": "Common Header\n\nBody two\nFooter"},
            {"page_number": 3, "text": "Common Header\n\nBody three\nFooter"},
        ]
        cleaned, diag = proc.strip_repeated_headers_footers(pages)
        self.assertEqual(diag["removed_header_count"], 3)
        self.assertEqual(diag["removed_footer_count"], 3)
        self.assertNotIn("Common Header", cleaned[0]["text"])

    def test_deterministic_chunk_ids_and_overlap(self) -> None:
        entry = self.entry()
        blocks = [
            {"paragraph_index": i, "text": f"{i}. " + ("word " * 80), "page_start": 1, "page_end": 1, "heading_path": ["JUDGMENT"], "block_type": "paragraph"}
            for i in range(5)
        ]
        first = proc.chunk_blocks(entry, blocks, target_tokens=120, max_tokens=220, overlap_tokens=80)
        second = proc.chunk_blocks(entry, blocks, target_tokens=120, max_tokens=220, overlap_tokens=80)
        self.assertEqual([c["chunk_id"] for c in first], [c["chunk_id"] for c in second])
        self.assertGreater(len(first), 1)
        self.assertLessEqual(max(c["estimated_token_count"] for c in first), 220)

    def test_oversized_paragraph_is_split(self) -> None:
        entry = self.entry()
        blocks = [{"paragraph_index": 0, "text": "word " * 500, "page_start": None, "page_end": None, "heading_path": [], "block_type": "paragraph"}]
        chunks = proc.chunk_blocks(entry, blocks, target_tokens=100, max_tokens=120, overlap_tokens=0)
        self.assertGreater(len(chunks), 1)

    def test_failure_isolation_for_missing_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = proc.process_document(self.entry(raw_path="missing.pdf"), root / "norm", root / "chunks", force=True)
            self.assertEqual(result["status"], "failed")

    def test_no_duplicate_chunk_ids_validation(self) -> None:
        entry = self.entry()
        blocks = [{"paragraph_index": 0, "text": "text", "page_start": None, "page_end": None, "heading_path": [], "block_type": "paragraph"}]
        chunks = [proc.make_chunk(entry, [], blocks), proc.make_chunk(entry, [], blocks)]
        with self.assertRaises(ValueError):
            proc.validate_chunks(entry, blocks, chunks)

    def test_no_provider_or_llm_dependency(self) -> None:
        with patch("builtins.__import__", side_effect=AssertionError("unexpected import")) as mocked:
            self.assertEqual(proc.estimated_tokens("one two"), 2)
            self.assertFalse(mocked.called)

    def entry(self, raw_path: str = "doc.pdf", mime: str = "application/pdf", text_source_type: str = "pdf_native") -> dict[str, object]:
        return {
            "document_id": "indian_kanoon:1",
            "provider": "indian_kanoon",
            "source_document_id": "1",
            "source_url": "https://indiankanoon.org/doc/1/",
            "case_title": "A vs B",
            "court": {"court_name": "Court", "court_level": "high_court"},
            "decision_date": "2024-01-01",
            "decision_year": 2024,
            "effective_offence_family": "homicide",
            "effective_legal_regime": "ipc_crpc",
            "temporal_track": "recent_ipc",
            "raw_path": raw_path,
            "raw_mime_type": mime,
            "sha256": "sha",
            "text_source_type": text_source_type,
            "human_review_source": "test",
            "human_review_status": "accepted",
            "automated": {},
            "attribution_text": "attr",
        }


if __name__ == "__main__":
    unittest.main()
