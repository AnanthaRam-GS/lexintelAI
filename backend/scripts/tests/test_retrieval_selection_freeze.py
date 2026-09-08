import json
from pathlib import Path
import unittest

from backend.app.services.reranking.base import RerankerConfig
from backend.app.services.retrieval.bm25 import DEFAULT_B, DEFAULT_K1, LEXICAL_INDEX_VERSION, TOKENIZER_VERSION
from backend.app.services.retrieval.service import HybridConfig, RetrievalService
from backend.scripts.build_vector_index import DEFAULT_COLLECTION


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"


class RetrievalSelectionFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((MANIFEST_DIR / "retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        cls.decision = json.loads((MANIFEST_DIR / "retrieval_tuning_decision.json").read_text(encoding="utf-8"))

    def test_selected_configuration_core_fields(self) -> None:
        self.assertEqual(self.config["selection_status"], "selected")
        self.assertEqual(self.config["candidate_depth"], 20)
        self.assertEqual(self.config["final_top_k"], 5)
        self.assertEqual(self.config["fusion"]["rrf_k"], 60)
        self.assertEqual(self.config["bm25"]["k1"], 1.5)
        self.assertEqual(self.config["bm25"]["b"], 0.75)

    def test_selected_models_and_indexes(self) -> None:
        self.assertEqual(self.config["dense"]["model"], "BAAI/bge-m3")
        self.assertEqual(self.config["dense"]["embedding_dimension"], 1024)
        self.assertTrue(self.config["dense"]["normalized_embeddings"])
        self.assertEqual(self.config["dense"]["index"], "legalai-chroma-index-v1")
        self.assertEqual(self.config["bm25"]["index"], LEXICAL_INDEX_VERSION)
        self.assertEqual(self.config["bm25"]["tokenizer"], TOKENIZER_VERSION)
        self.assertEqual(DEFAULT_COLLECTION, "legalai_trusted_judgments_v1")
        self.assertEqual(self.config["reranker"]["model"], "BAAI/bge-reranker-v2-m3")
        self.assertEqual(self.config["reranker"]["max_length"], 512)
        self.assertEqual(self.config["reranker"]["batch_size"], 8)

    def test_experimental_features_are_disabled(self) -> None:
        flags = self.config["experimental_features"]
        self.assertFalse(flags["regime_ranking_enabled"])
        self.assertFalse(flags["query_expansion_enabled"])
        self.assertFalse(flags["metadata_reranking_enabled"])
        for status in self.decision["experimental_features"].values():
            self.assertTrue(status["implemented"])
            self.assertFalse(status["default_enabled"])

    def test_default_runtime_config_matches_freeze(self) -> None:
        service = RetrievalService()
        self.assertEqual(HybridConfig().rrf_k, self.config["fusion"]["rrf_k"])
        self.assertEqual(HybridConfig().candidate_k, self.config["candidate_depth"])
        self.assertEqual(service.hybrid_config.rrf_k, 60)
        self.assertEqual(RerankerConfig().model_name, self.config["reranker"]["model"])
        self.assertEqual(RerankerConfig().max_length, self.config["reranker"]["max_length"])
        self.assertEqual(RerankerConfig().batch_size, self.config["reranker"]["batch_size"])
        self.assertEqual(DEFAULT_K1, self.config["bm25"]["k1"])
        self.assertEqual(DEFAULT_B, self.config["bm25"]["b"])

    def test_tuning_decision_freezes_baseline(self) -> None:
        self.assertEqual(self.decision["final_decision"], "RETAIN_UNTUNED_HYBRID_RERANK")
        self.assertFalse(self.decision["further_phase0_retrieval_tuning"])
        self.assertFalse(self.decision["frozen_benchmark_rerun_required"])
        self.assertEqual(self.decision["baseline_configuration"]["rrf_k"], 60)
        self.assertEqual(self.decision["baseline_configuration"]["final_top_k"], 5)

    def test_source_does_not_enable_experimental_paths_by_default(self) -> None:
        source = (REPO_ROOT / "backend/app/services/retrieval/service.py").read_text(encoding="utf-8")
        self.assertNotIn("legal_query_expansion", source)
        self.assertNotIn("retrieval_metadata_intent", source)
        self.assertNotIn("regime_ranking_enabled", source)


if __name__ == "__main__":
    unittest.main()
