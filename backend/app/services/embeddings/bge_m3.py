"""Optional BGE-M3 embedding provider.

This module avoids importing model libraries at package import time so offline
tests can run without downloading or loading any external model.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.services.embeddings.base import EmbeddingConfig, validate_vectors
from backend.app.services.model_device import DeviceFallbackModel


def resolve_model_name_or_path(model_name: str) -> str:
    if model_name != "BAAI/bge-m3":
        return model_name
    cache_root = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-m3"
    refs_main = cache_root / "refs/main"
    if refs_main.exists():
        revision = refs_main.read_text(encoding="utf-8").strip()
        snapshot = cache_root / "snapshots" / revision
        required = [
            "config.json",
            "pytorch_model.bin",
            "sentencepiece.bpe.model",
            "tokenizer.json",
            "tokenizer_config.json",
            "sparse_linear.pt",
            "colbert_linear.pt",
        ]
        if all((snapshot / name).exists() for name in required):
            return str(snapshot)
    return model_name


class BgeM3EmbeddingProvider:
    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding is required for real BGE-M3 embeddings") from exc
        model_path = resolve_model_name_or_path(config.model_name)
        # FlagEmbedding takes ``devices``; with none given it picks an accelerator itself.
        self._runtime = DeviceFallbackModel(
            "bge-m3",
            config.device,
            config.use_fp16,
            lambda device, use_fp16: BGEM3FlagModel(model_path, use_fp16=use_fp16, devices=device),
        )
        self._dimension: int | None = config.dimension

    @property
    def device(self) -> str:
        return self._runtime.device

    @property
    def precision(self) -> str:
        return self._runtime.precision

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
        encoded = self._runtime.run(
            lambda model: model.encode(
                texts,
                batch_size=self._config.batch_size,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
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
