"""Tests for the bounded, temporary private-PDF chunking and query-focused
retrieval pipeline. No live provider calls anywhere in this file - this
module makes no provider calls at all (local_document_map.py's tests cover
the entirely-local whole-document analysis that replaced the old per-batch
generative Stage-1 approach)."""

from __future__ import annotations

import unittest

from backend.app.services.private_pdf_rag import (
    PrivateChunk,
    build_private_chunks,
    render_private_evidence_block,
    select_query_focused_private_evidence,
)


def raw_chunk(text: str, *, page: int = 1, token_count: int | None = None) -> dict:
    return {"text": text, "page_start": page, "page_end": page, "token_count": token_count}


# ---------------------------------------------------------------------------
# Private chunking
# ---------------------------------------------------------------------------


class PrivateChunkingTests(unittest.TestCase):
    def test_pdf_split_into_bounded_chunks_with_stable_p_ids(self) -> None:
        chunks = build_private_chunks([raw_chunk(f"text {i}", page=i) for i in range(1, 6)])
        self.assertEqual([c.private_chunk_id for c in chunks], ["P1", "P2", "P3", "P4", "P5"])

    def test_chunk_ids_are_request_local_never_reused_as_trusted_ids(self) -> None:
        chunks = build_private_chunks([raw_chunk("text")])
        self.assertTrue(chunks[0].private_chunk_id.startswith("P"))
        self.assertFalse(chunks[0].private_chunk_id.startswith("E"))

    def test_page_metadata_preserved_where_available(self) -> None:
        chunks = build_private_chunks([raw_chunk("text", page=7)])
        self.assertEqual(chunks[0].page_start, 7)
        self.assertEqual(chunks[0].page_end, 7)

    def test_page_metadata_absent_is_tolerated(self) -> None:
        chunks = build_private_chunks([{"text": "text with no page info"}])
        self.assertIsNone(chunks[0].page_start)
        self.assertIsNone(chunks[0].page_end)

    def test_empty_chunk_text_is_dropped_not_kept_as_a_blank_chunk(self) -> None:
        chunks = build_private_chunks([raw_chunk(""), raw_chunk("real text")])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "real text")

    def test_empty_input_list_produces_no_chunks(self) -> None:
        self.assertEqual(build_private_chunks([]), [])

    def test_token_count_falls_back_to_estimator_when_absent(self) -> None:
        chunks = build_private_chunks([raw_chunk("some words here", token_count=None)])
        self.assertGreater(chunks[0].token_count, 0)

    def test_token_count_uses_upstream_chunker_value_when_present(self) -> None:
        chunks = build_private_chunks([raw_chunk("text", token_count=42)])
        self.assertEqual(chunks[0].token_count, 42)


# ---------------------------------------------------------------------------
# Query-focused private retrieval
# ---------------------------------------------------------------------------


class PrivateRetrievalTests(unittest.TestCase):
    def make_chunks(self, n: int = 10) -> list[PrivateChunk]:
        raw = [
            raw_chunk(f"chunk {i} discusses bail application procedure under Section 302 IPC.", page=i, token_count=50)
            for i in range(1, n + 1)
        ]
        # One chunk far from the others is about something unrelated.
        raw.append(raw_chunk("this chunk is entirely about unrelated tax filing deadlines.", page=99, token_count=50))
        return build_private_chunks(raw)

    def test_query_selects_relevant_chunks_over_irrelevant_ones(self) -> None:
        chunks = self.make_chunks()
        selected = select_query_focused_private_evidence(
            chunks, "bail application Section 302 IPC", dense_provider=None, top_k=3, token_budget_tokens=1000
        )
        selected_texts = " ".join(item.chunk.text for item in selected)
        self.assertIn("bail application", selected_texts)
        self.assertNotIn("tax filing", selected_texts)

    def test_top_k_is_enforced(self) -> None:
        chunks = self.make_chunks()
        selected = select_query_focused_private_evidence(
            chunks, "bail", dense_provider=None, top_k=2, token_budget_tokens=100000
        )
        self.assertLessEqual(len(selected), 2)

    def test_token_budget_is_enforced_even_under_top_k(self) -> None:
        chunks = self.make_chunks()
        selected = select_query_focused_private_evidence(
            chunks, "bail", dense_provider=None, top_k=100, token_budget_tokens=120
        )
        self.assertLessEqual(sum(item.chunk.token_count for item in selected), 120)

    def test_zero_budget_selects_nothing(self) -> None:
        chunks = self.make_chunks()
        selected = select_query_focused_private_evidence(
            chunks, "bail", dense_provider=None, top_k=10, token_budget_tokens=0
        )
        self.assertEqual(selected, [])

    def test_empty_chunk_list_selects_nothing(self) -> None:
        selected = select_query_focused_private_evidence(
            [], "bail", dense_provider=None, top_k=10, token_budget_tokens=1000
        )
        self.assertEqual(selected, [])

    def test_adjacent_overlapping_high_scoring_chunks_do_not_dominate_selection(self) -> None:
        # All chunks score identically (same repeated text), so without the
        # diversity heuristic the top-k would just be the first k adjacent
        # chunks. With it, selection should skip immediate neighbors.
        raw = [raw_chunk("bail application Section 302 IPC custody remand", page=i, token_count=10) for i in range(1, 11)]
        chunks = build_private_chunks(raw)
        selected = select_query_focused_private_evidence(
            chunks, "bail application Section 302 IPC custody remand", dense_provider=None, top_k=5, token_budget_tokens=1000
        )
        indexes = sorted(item.chunk.chunk_index for item in selected)
        for a, b in zip(indexes, indexes[1:]):
            self.assertGreater(b - a, 1, "adjacent chunks must not both be selected when scores tie")

    def test_selection_is_deterministic_across_repeated_calls(self) -> None:
        chunks = self.make_chunks()
        first = select_query_focused_private_evidence(chunks, "bail", dense_provider=None, top_k=5, token_budget_tokens=500)
        second = select_query_focused_private_evidence(chunks, "bail", dense_provider=None, top_k=5, token_budget_tokens=500)
        self.assertEqual([i.chunk.private_chunk_id for i in first], [i.chunk.private_chunk_id for i in second])

    def test_dense_provider_failure_falls_back_to_lexical_scoring_without_raising(self) -> None:
        class ExplodingProvider:
            def embed_query(self, text):
                raise RuntimeError("embedding backend unavailable")

            def embed_documents(self, texts):
                raise RuntimeError("embedding backend unavailable")

        chunks = self.make_chunks()
        selected = select_query_focused_private_evidence(
            chunks, "bail application", dense_provider=ExplodingProvider(), top_k=3, token_budget_tokens=1000
        )
        self.assertGreater(len(selected), 0)

    def test_dense_provider_is_used_when_available(self) -> None:
        class FakeDenseProvider:
            """Deterministic fake: embeds any chunk containing 'bail' as the
            same vector as the query, and everything else as orthogonal -
            lets us assert dense scoring (not lexical overlap) drove the
            ranking, by making lexical overlap point the opposite way."""

            def embed_query(self, text):
                return [1.0, 0.0]

            def embed_documents(self, texts):
                return [[1.0, 0.0] if "bail" in text else [0.0, 1.0] for text in texts]

        # Lexically, the query shares words with chunk 0 ("apple banana"), not
        # chunk 1. The fake dense provider says the opposite: chunk 1 matches.
        raw = [raw_chunk("apple banana unrelated filler content", page=1, token_count=10)]
        raw.append(raw_chunk("bail bail bail bail bail bail bail bail bail bail", page=2, token_count=10))
        chunks = build_private_chunks(raw)
        selected = select_query_focused_private_evidence(
            chunks, "apple banana", dense_provider=FakeDenseProvider(), top_k=1, token_budget_tokens=1000
        )
        self.assertEqual(selected[0].chunk.chunk_index, 1, "dense scoring, not lexical overlap, must drive selection when a dense provider is available")

    def test_no_global_chroma_or_bm25_mutation(self) -> None:
        from unittest.mock import patch

        chunks = self.make_chunks()
        with patch("backend.app.services.vector_store.ChromaVectorStore.upsert_chunks") as upsert, patch(
            "backend.app.services.ingestion.create_ingestion_job"
        ) as create_job:
            select_query_focused_private_evidence(chunks, "bail", dense_provider=None, top_k=5, token_budget_tokens=1000)
        upsert.assert_not_called()
        create_job.assert_not_called()


class RenderPrivateEvidenceBlockTests(unittest.TestCase):
    def test_marks_evidence_as_non_authoritative(self) -> None:
        chunks = build_private_chunks([raw_chunk("some fact")])
        selected = select_query_focused_private_evidence(chunks, "fact", dense_provider=None, top_k=1, token_budget_tokens=1000)
        block = render_private_evidence_block(selected, filename="doc.pdf")
        self.assertIn("never legal authority", block)
        self.assertIn("must never", block)

    def test_empty_selection_renders_empty_string(self) -> None:
        self.assertEqual(render_private_evidence_block([], filename="doc.pdf"), "")


# ---------------------------------------------------------------------------
# Hierarchical whole-document analysis
# ---------------------------------------------------------------------------


class TraceabilityTests(unittest.TestCase):
    def test_private_ids_never_look_like_trusted_evidence_ids(self) -> None:
        chunks = build_private_chunks([raw_chunk("text")])
        for chunk in chunks:
            self.assertRegex(chunk.private_chunk_id, r"^P\d+$")
            self.assertNotRegex(chunk.private_chunk_id, r"^E\d+$")


if __name__ == "__main__":
    unittest.main()
