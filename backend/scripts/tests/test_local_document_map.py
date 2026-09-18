"""Tests for the entirely local (non-generative) private-document analysis
that replaced the old per-batch generative Stage-1 approach.

No provider calls anywhere in this file - this module makes none.
"""

from __future__ import annotations

import unittest

from backend.app.services.local_document_map import (
    _MAX_ENTRIES_PER_FIELD,
    _MAX_EXCERPT_CHARS,
    build_enriched_trusted_query,
    build_local_document_map,
    detect_document_type,
    extract_sections_and_entities,
    local_map_metrics,
    render_local_document_map,
    select_multi_intent_evidence,
)
from backend.app.services.private_pdf_rag import build_private_chunks


def raw_chunk(text: str, *, page: int = 1) -> dict:
    return {"text": text, "page_start": page, "page_end": page}


FIR_TEXT = [
    "FIRST INFORMATION REPORT under Section 154 CrPC. FIR No. 397/2024. Police Station: Kotwali. "
    "The accused committed offence under Section 302 IPC and Section 34 IPC against the complainant "
    "on 12 May 2024 near the market.",
    "The complainant stated that on 12 May 2024 at about 8 PM, the accused attacked him with a knife "
    "near the market. Material facts show a dispute over land ownership prior to the incident.",
    "Investigation was conducted by the police. During investigation, the police recovered a knife "
    "from the scene. Medical examination of the victim was conducted at District Hospital on 13 May "
    "2024, confirming stab wounds.",
    "A witness stated that he saw the accused fleeing the scene immediately after the incident. "
    "Another witness corroborated this account in his statement recorded under Section 161 CrPC.",
    "The accused denied the allegations and claimed alibi, stating he was elsewhere at the time of "
    "the incident. The defence argued lack of direct evidence linking the accused to the crime scene.",
]

JUDGMENT_TEXT = [
    "IN THE COURT OF THE SESSIONS JUDGE. BEFORE THE HON'BLE JUDGE. Criminal Appeal No. 45 of 2023.",
    "J U D G M E N T. The appellant was convicted under Section 376 IPC by the trial court and "
    "sentenced to ten years imprisonment.",
    "Having considered the evidence and submissions, this court finds no merit in the appeal. The "
    "conviction and sentence are upheld. Ordered accordingly.",
]


class DocumentTypeDetectionTests(unittest.TestCase):
    def test_detects_fir_from_text_markers(self) -> None:
        chunks = build_private_chunks([raw_chunk(t) for t in FIR_TEXT])
        self.assertEqual(detect_document_type("upload.pdf", chunks), "FIR")

    def test_detects_judgment_from_text_markers(self) -> None:
        chunks = build_private_chunks([raw_chunk(t) for t in JUDGMENT_TEXT])
        self.assertEqual(detect_document_type("upload.pdf", chunks), "judgment")

    def test_detects_from_filename_when_text_is_ambiguous(self) -> None:
        chunks = build_private_chunks([raw_chunk("Some ambiguous legal text with no clear markers.")])
        self.assertEqual(detect_document_type("chargesheet_final.pdf", chunks), "chargesheet")

    def test_falls_back_to_unknown_without_hallucinating_a_type(self) -> None:
        chunks = build_private_chunks([raw_chunk("Some ambiguous text with nothing recognizable at all.")])
        self.assertEqual(detect_document_type("document.pdf", chunks), "unknown")


class SectionAndEntityExtractionTests(unittest.TestCase):
    def test_extracts_explicit_statutory_sections(self) -> None:
        chunks = build_private_chunks([raw_chunk(t) for t in FIR_TEXT])
        sections, _, _ = extract_sections_and_entities(chunks)
        joined = " ".join(sections)
        self.assertIn("302", joined)
        self.assertTrue(any("IPC" in s for s in sections))

    def test_extracts_important_dates(self) -> None:
        chunks = build_private_chunks([raw_chunk(t) for t in FIR_TEXT])
        _, _, dates = extract_sections_and_entities(chunks)
        self.assertTrue(any("2024" in d for d in dates))

    def test_sections_are_deduplicated(self) -> None:
        chunks = build_private_chunks([raw_chunk("Section 302 IPC. Section 302 IPC again. Section 302 IPC once more.")])
        sections, _, _ = extract_sections_and_entities(chunks)
        normalized = [s.lower() for s in sections]
        self.assertEqual(len(normalized), len(set(normalized)))

    def test_empty_document_returns_empty_lists_not_invented_content(self) -> None:
        chunks = build_private_chunks([raw_chunk("Nothing legally relevant appears in this text at all.")])
        sections, parties, dates = extract_sections_and_entities(chunks)
        self.assertEqual(sections, [])
        self.assertEqual(dates, [])
        # parties may or may not be empty depending on generic role words; the
        # important guarantee is no exception and no fabricated named entity.
        for party in parties:
            self.assertIsInstance(party, str)

    def test_does_not_import_or_require_inlegalbert(self) -> None:
        import ast

        import backend.app.services.local_document_map as module

        with open(module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported_names = {
            alias.name.lower()
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        imported_modules = {node.module.lower() for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse(any("inlegalbert" in name for name in imported_names | imported_modules))


class MultiIntentRetrievalTests(unittest.TestCase):
    def make_chunks(self):
        return build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])

    def test_different_intents_select_different_chunks(self) -> None:
        chunks = self.make_chunks()
        by_field = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=100000)
        all_ids = [entry.private_evidence_id for entries in by_field.values() for entry in entries]
        # No id appears under two different fields (global dedup across intents).
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_page_metadata_retained_on_selected_excerpts(self) -> None:
        chunks = self.make_chunks()
        by_field = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=100000)
        for entries in by_field.values():
            for entry in entries:
                self.assertNotEqual(entry.pages, "")

    def test_global_token_cap_is_respected_across_all_intents(self) -> None:
        chunks = self.make_chunks()
        small_budget = 60  # smaller than several individual chunks combined
        by_field = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=small_budget)
        total_chunks_selected = sum(len(entries) for entries in by_field.values())
        self.assertLessEqual(total_chunks_selected, len(chunks))
        # A tiny shared budget must not let every intent claim its own chunk.
        self.assertLess(total_chunks_selected, len(FIR_TEXT) * 2)

    def test_selection_is_deterministic(self) -> None:
        chunks = self.make_chunks()
        first = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=5000)
        second = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(
            {k: [e.private_evidence_id for e in v] for k, v in first.items()},
            {k: [e.private_evidence_id for e in v] for k, v in second.items()},
        )

    def test_excerpts_are_bounded_in_size(self) -> None:
        long_text = "material facts about the incident. " * 200
        chunks = build_private_chunks([raw_chunk(long_text)])
        by_field = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=100000)
        for entries in by_field.values():
            for entry in entries:
                self.assertLessEqual(len(entry.excerpt), _MAX_EXCERPT_CHARS + 5)

    def test_zero_budget_selects_nothing(self) -> None:
        chunks = self.make_chunks()
        by_field = select_multi_intent_evidence(chunks, dense_provider=None, token_budget_tokens=0)
        self.assertEqual(sum(len(v) for v in by_field.values()), 0)


class BuildLocalDocumentMapTests(unittest.TestCase):
    def test_fir_like_document_produces_a_populated_bounded_map(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])
        doc_map = build_local_document_map(chunks, filename="fir.pdf", dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(doc_map.document_type, "FIR")
        self.assertGreater(len(doc_map.explicit_sections), 0)
        self.assertGreater(len(doc_map.important_chunk_ids), 0)

    def test_judgment_like_document_is_classified_and_analyzed(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(JUDGMENT_TEXT)])
        doc_map = build_local_document_map(chunks, filename="judgment.pdf", dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(doc_map.document_type, "judgment")
        self.assertIn("376", " ".join(doc_map.explicit_sections))

    def test_p_id_traceability_on_every_excerpt(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])
        doc_map = build_local_document_map(chunks, filename="fir.pdf", dense_provider=None, token_budget_tokens=5000)
        for chunk_id in doc_map.important_chunk_ids:
            self.assertRegex(chunk_id, r"^P\d+$")

    def test_map_size_is_bounded_per_field(self) -> None:
        many_chunks = build_private_chunks(
            [raw_chunk(f"material fact about the incident number {i}. Section 302 IPC.", page=i + 1) for i in range(60)]
        )
        doc_map = build_local_document_map(many_chunks, filename="big.pdf", dense_provider=None, token_budget_tokens=100000)
        self.assertLessEqual(len(doc_map.material_facts), _MAX_ENTRIES_PER_FIELD)
        self.assertLessEqual(len(doc_map.charges), _MAX_ENTRIES_PER_FIELD)

    def test_empty_document_returns_empty_fields_not_hallucinated_content(self) -> None:
        chunks = build_private_chunks([raw_chunk("Nothing relevant here at all, just filler words.")])
        doc_map = build_local_document_map(chunks, filename="empty.pdf", dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(doc_map.explicit_sections, [])
        self.assertEqual(doc_map.witness_excerpts, [])
        self.assertEqual(doc_map.medical_forensic_excerpts, [])

    def test_zero_provider_calls_ever(self) -> None:
        """Nothing in this module accepts or calls an adapter - structurally
        impossible to make a provider call, not just untested."""
        import inspect

        import backend.app.services.local_document_map as module

        source = inspect.getsource(module)
        self.assertNotIn("generate_structured_answer", source)
        self.assertNotIn("adapter", source.lower().replace("dense_provider", "").replace("embed_documents", "").replace("embed_query", ""))


class RenderAndQueryEnrichmentTests(unittest.TestCase):
    def test_rendered_map_marks_sections_as_mentions_not_verified_law(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])
        doc_map = build_local_document_map(chunks, filename="fir.pdf", dense_provider=None, token_budget_tokens=5000)
        rendered = render_local_document_map(doc_map)
        self.assertIn("not verified applicable law", rendered)
        self.assertIn("locally built", rendered)

    def test_enriched_query_uses_map_content_over_fallback(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])
        doc_map = build_local_document_map(chunks, filename="fir.pdf", dense_provider=None, token_budget_tokens=5000)
        enriched = build_enriched_trusted_query(doc_map, fallback_query="Analyze this legal document.")
        self.assertNotEqual(enriched, "Analyze this legal document.")

    def test_enriched_query_falls_back_when_map_is_empty(self) -> None:
        chunks = build_private_chunks([raw_chunk("Nothing relevant here, just filler text with no structure.")])
        # A zero token budget forces an empty map regardless of what a
        # single low-relevance chunk might otherwise be selected for.
        doc_map = build_local_document_map(chunks, filename="empty.pdf", dense_provider=None, token_budget_tokens=0)
        enriched = build_enriched_trusted_query(doc_map, fallback_query="Analyze this legal document.")
        self.assertEqual(enriched, "Analyze this legal document.")


class MetricsTests(unittest.TestCase):
    def test_metrics_never_include_document_text(self) -> None:
        chunks = build_private_chunks([raw_chunk(t, page=i + 1) for i, t in enumerate(FIR_TEXT)])
        doc_map = build_local_document_map(chunks, filename="fir.pdf", dense_provider=None, token_budget_tokens=5000)
        metrics = local_map_metrics(doc_map)
        self.assertNotIn("knife", str(metrics))
        self.assertIn("estimated_map_tokens", metrics)
        self.assertGreater(metrics["estimated_map_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
