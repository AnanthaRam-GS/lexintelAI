import hashlib
import json
import unittest
from pathlib import Path

from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import (
    FROZEN_CANDIDATE_DEPTH,
    FROZEN_FINAL_TOP_K,
    FROZEN_RERANKER_MODEL,
    FROZEN_RETRIEVAL_DECISION,
    FROZEN_RRF_K,
    LEGAL_RAG_RETRIEVAL_VERSION,
    retrieve_legal_evidence,
)
from backend.app.services.retrieval.service import RetrievalResponse, RetrievalTrace
from backend.app.services.vector_store import RetrievalResult


REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeRetrievalService:
    def __init__(self, results=None, fail=False) -> None:
        self.results = results if results is not None else [result("doc:1:chunk:0000", 1)]
        self.fail = fail
        self.calls = []

    def retrieve(self, query, mode="hybrid", top_k=5, candidate_k=None, filters=None, rerank=False):
        self.calls.append(
            {
                "query": query,
                "mode": mode,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "filters": filters,
                "rerank": rerank,
            }
        )
        if self.fail:
            raise RuntimeError("dense provider and vector store are required for dense retrieval")
        returned = self.results[:top_k]
        trace = RetrievalTrace(
            query=query,
            mode=mode,
            candidate_k=candidate_k or FROZEN_CANDIDATE_DEPTH,
            top_k=top_k,
            dense_latency_ms=3.0,
            dense_embedding_latency_ms=1.0,
            dense_query_latency_ms=2.0,
            lexical_latency_ms=4.0,
            fusion_latency_ms=0.5,
            rerank_latency_ms=5.0,
            total_latency_ms=12.5,
            dense_candidate_count=min(20, len(self.results) + 1),
            lexical_candidate_count=min(20, len(self.results) + 2),
            fused_candidate_count=min(20, len(self.results) + 3),
            filters=filters,
            rerank=rerank,
        )
        return RetrievalResponse(results=returned, trace=trace)


def result(chunk_id: str, rank: int, missing_case=False) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id=chunk_id.split(":chunk:", 1)[0],
        text=f"Stored normalized chunk text for {chunk_id}",
        score=2.0,
        rank=rank,
        case_title=None if missing_case else f"Case {chunk_id}",
        court={"court_name": "High Court", "court_level": "high_court"},
        decision_date="2025-01-01",
        source_url="https://example.test/judgment",
        page_start=1,
        page_end=2,
        paragraph_start=10,
        paragraph_end=12,
        effective_offence_family="homicide",
        effective_legal_regime="ipc_crpc",
        text_source_type="pdf_native",
        retrieval_mode="hybrid",
        dense_rank=rank,
        dense_score=0.8,
        lexical_rank=rank + 1,
        lexical_score=3.5,
        hybrid_score=0.03,
        rerank_score=7.5,
        rerank_rank=rank,
        pre_rerank_rank=rank + 2,
        pre_rerank_score=0.03,
    )


class LegalRagRetrievalTests(unittest.TestCase):
    def understanding(self):
        return understand_legal_query("Section 302 IPC murder bail before Sessions Court")

    def test_schema_and_frozen_config(self) -> None:
        response = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService())
        self.assertEqual(response.schema_version, LEGAL_RAG_RETRIEVAL_VERSION)
        self.assertEqual(response.frozen_config.decision, FROZEN_RETRIEVAL_DECISION)
        self.assertEqual(response.frozen_config.rrf_k, FROZEN_RRF_K)
        self.assertEqual(response.frozen_config.candidate_depth, FROZEN_CANDIDATE_DEPTH)
        self.assertEqual(response.frozen_config.final_top_k, FROZEN_FINAL_TOP_K)
        self.assertEqual(response.frozen_config.reranker_model, FROZEN_RERANKER_MODEL)
        self.assertFalse(response.frozen_config.query_expansion_enabled)
        self.assertFalse(response.frozen_config.legal_regime_ranking_enabled)
        self.assertFalse(response.frozen_config.metadata_reranking_enabled)

    def test_original_query_used_for_hybrid_dense_bm25_and_rerank(self) -> None:
        understanding = self.understanding()
        service = FakeRetrievalService()
        response = retrieve_legal_evidence(understanding, retrieval_service=service)
        self.assertEqual(service.calls[0]["query"], understanding.query)
        self.assertEqual(service.calls[0]["mode"], "hybrid")
        self.assertEqual(service.calls[0]["candidate_k"], 20)
        self.assertEqual(service.calls[0]["top_k"], 5)
        self.assertTrue(service.calls[0]["rerank"])
        self.assertIsNone(service.calls[0]["filters"])
        self.assertEqual(response.understanding_summary["retrieval_query_policy"], "original_query_only")
        self.assertFalse(response.understanding_summary["query_expansion_enabled"])

    def test_evidence_preserves_stage_scores_and_citation_metadata(self) -> None:
        response = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService([result("doc:1:chunk:0000", 1)]))
        evidence = response.evidence[0]
        self.assertEqual(evidence.citation_id, "E1")
        self.assertEqual(evidence.text, "Stored normalized chunk text for doc:1:chunk:0000")
        self.assertEqual(evidence.bm25_rank, 2)
        self.assertEqual(evidence.dense_rank, 1)
        self.assertEqual(evidence.rrf_rank, 3)
        self.assertEqual(evidence.reranker_rank, 1)
        self.assertEqual(evidence.reranker_score, 7.5)
        self.assertEqual(evidence.citation_metadata.judgment_id, "doc:1")
        self.assertEqual(evidence.citation_metadata.paragraph_start, 10)

    def test_stage_counts_timings_provenance_and_serialization(self) -> None:
        response = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService([result("doc:1:chunk:0000", 1), result("doc:2:chunk:0000", 2)]))
        self.assertLessEqual(response.stage_counts.bm25_returned, 20)
        self.assertLessEqual(response.stage_counts.dense_returned, 20)
        self.assertLessEqual(response.stage_counts.rrf_unique_candidates, 20)
        self.assertEqual(response.stage_counts.final_evidence_count, 2)
        self.assertGreaterEqual(response.timings.bm25_ms, 0.0)
        self.assertGreaterEqual(response.timings.reranker_ms, 0.0)
        self.assertIn("bm25", {item.stage for item in response.provenance})
        self.assertIn("dense", {item.stage for item in response.provenance})
        self.assertIn("fusion", {item.stage for item in response.provenance})
        self.assertIn("reranker", {item.stage for item in response.provenance})
        json.loads(response.model_dump_json())

    def test_incomplete_provenance_warning_and_no_results(self) -> None:
        incomplete = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService([result("doc:1:chunk:0000", 1, missing_case=True)]))
        self.assertEqual(incomplete.warnings[0].code, "INCOMPLETE_EVIDENCE_PROVENANCE")

        empty = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService([]))
        self.assertEqual(empty.evidence, [])
        self.assertIn("NO_RETRIEVAL_RESULTS", {warning.code for warning in empty.warnings})

    def test_whitespace_query_skips_expensive_retrieval(self) -> None:
        understanding = understand_legal_query("   ")
        service = FakeRetrievalService()
        response = retrieve_legal_evidence(understanding, retrieval_service=service)
        self.assertEqual(service.calls, [])
        self.assertEqual(response.evidence, [])
        self.assertEqual(response.stage_counts.final_evidence_count, 0)
        self.assertIn("NO_RETRIEVAL_RESULTS", {warning.code for warning in response.warnings})

    def test_stage_failure_is_structured_error_not_hidden_fallback(self) -> None:
        response = retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService(fail=True))
        self.assertEqual(response.evidence, [])
        self.assertEqual(response.error.code, "DENSE_INDEX_UNAVAILABLE")
        self.assertEqual(response.error.stage, "dense")
        self.assertFalse(response.error.fallback_used)
        self.assertEqual(response.fallbacks, [])
        self.assertIn("DENSE_INDEX_UNAVAILABLE", {warning.code for warning in response.warnings})

    def test_top_k_and_candidate_depth_are_frozen(self) -> None:
        with self.assertRaises(ValueError):
            retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService(), top_k=6)
        with self.assertRaises(ValueError):
            retrieve_legal_evidence(self.understanding(), retrieval_service=FakeRetrievalService(), candidate_depth=10)

    def test_no_llm_or_retrieval_expansion_artifacts_and_freezes_unchanged(self) -> None:
        expected = {
            "data/structured/manifests/retrieval_selected_configuration.json": "31f6ce663e76e3934ec47935174636964227d56a7eb41256ee520c0152feb7fc",
            "data/structured/manifests/retrieval_tuning_decision.json": "74797ef01c3af17b62fde6a3216a0999eee3f1b3dbbbd22b470c2e3f4bb6524e",
            "data/structured/manifests/legal_section_selected_configuration.json": "9b1b3902a30a70890edb88043c07971b10ef6796340cff92cad5ffcabdfb969e",
            "data/structured/manifests/legal_ner_selected_configuration.json": "45b1e3f8282e58cf99c621e4f7d8d909c3f88549b2c850310ea333cfeafaf2d9",
            "backend/app/services/legal_section_prediction.py": "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c",
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
