"""BGE reranker provider backed by FlagEmbedding."""

from __future__ import annotations

from pathlib import Path

from backend.app.services.reranking.base import Reranker, RerankerConfig
from backend.app.services.vector_store import RetrievalResult


def resolve_reranker_model_name_or_path(model_name: str) -> str:
    if model_name != "BAAI/bge-reranker-v2-m3":
        return model_name
    cache_root = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3"
    refs_main = cache_root / "refs/main"
    if refs_main.exists():
        revision = refs_main.read_text(encoding="utf-8").strip()
        snapshot = cache_root / "snapshots" / revision
        if (snapshot / "config.json").exists() and ((snapshot / "model.safetensors").exists() or (snapshot / "pytorch_model.bin").exists()):
            return str(snapshot)
    return model_name


class BgeReranker(Reranker):
    def __init__(self, config: RerankerConfig) -> None:
        self.config = config
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding is required for BGE reranking") from exc
        self._model = FlagReranker(
            resolve_reranker_model_name_or_path(config.model_name),
            use_fp16=False,
            devices=config.device,
            batch_size=config.batch_size,
            max_length=config.max_length,
        )

    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        pairs = [(query, candidate.text) for candidate in candidates]
        scores = self._model.compute_score(pairs, batch_size=self.config.batch_size, max_length=self.config.max_length)
        if isinstance(scores, float):
            return [float(scores)]
        return [float(score) for score in scores]
