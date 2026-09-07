"""Deterministic mock reranker for network-free tests."""

from __future__ import annotations

import hashlib

from backend.app.services.reranking.base import Reranker, RerankerConfig
from backend.app.services.vector_store import RetrievalResult


class DeterministicMockReranker(Reranker):
    def __init__(self, config: RerankerConfig | None = None) -> None:
        self.config = config or RerankerConfig(model_name="deterministic-mock-reranker")

    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        scores: list[float] = []
        for candidate in candidates:
            payload = f"{query}\n{candidate.chunk_id}\n{candidate.text}".encode("utf-8")
            digest = hashlib.sha256(payload).digest()
            scores.append(int.from_bytes(digest[:8], "big") / 2**64)
        return scores
