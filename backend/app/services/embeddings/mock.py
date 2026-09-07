"""Deterministic offline embedding provider for tests and architecture validation."""

from __future__ import annotations

import hashlib

from backend.app.services.embeddings.base import EmbeddingConfig, l2_normalize, validate_vectors


class DeterministicMockEmbeddingProvider:
    """Stable hash-based vectors; useful only for tests, never semantic quality."""

    def __init__(self, config: EmbeddingConfig | None = None, dimension: int = 32) -> None:
        self._config = config or EmbeddingConfig(model_name="deterministic-mock", dimension=dimension)
        self._dimension = self._config.dimension or dimension

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def embedding_dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = [self._embed(text) for text in texts]
        validate_vectors(vectors, self._dimension)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _embed(self, text: str) -> list[float]:
        values: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < self._dimension:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for byte in digest:
                values.append((byte / 127.5) - 1.0)
                if len(values) == self._dimension:
                    break
            counter += 1
        if self._config.normalize_embeddings:
            values = l2_normalize(values)
        return values
