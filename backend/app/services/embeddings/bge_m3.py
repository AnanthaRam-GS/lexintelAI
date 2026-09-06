"""Optional BGE-M3 embedding provider.

This module avoids importing model libraries at package import time so offline
tests can run without downloading or loading any external model.
"""

from __future__ import annotations

from backend.app.services.embeddings.base import EmbeddingConfig, validate_vectors


class BgeM3EmbeddingProvider:
    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding is required for real BGE-M3 embeddings") from exc
        self._model = BGEM3FlagModel(config.model_name, use_fp16=False, device=config.device)
        self._dimension: int | None = config.dimension

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def embedding_dimension(self) -> int:
        if self._dimension is None:
            vector = self.embed_query("dimension probe")
            self._dimension = len(vector)
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        encoded = self._model.encode(
            texts,
            batch_size=self._config.batch_size,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vectors = encoded["dense_vecs"].tolist()
        if self._config.normalize_embeddings:
            from backend.app.services.embeddings.base import l2_normalize

            vectors = [l2_normalize([float(value) for value in vector]) for vector in vectors]
        else:
            vectors = [[float(value) for value in vector] for vector in vectors]
        self._dimension = validate_vectors(vectors, self._dimension)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
