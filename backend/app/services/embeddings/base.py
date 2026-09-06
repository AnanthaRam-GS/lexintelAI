"""Embedding provider contracts and shared helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = "BAAI/bge-m3"
    device: str = "cpu"
    batch_size: int = 16
    normalize_embeddings: bool = True
    dimension: int | None = None


class EmbeddingProvider(Protocol):
    @property
    def config(self) -> EmbeddingConfig:
        ...

    @property
    def embedding_dimension(self) -> int:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def validate_vectors(vectors: list[list[float]], expected_dimension: int | None = None) -> int:
    if not vectors:
        return expected_dimension or 0
    dimension = len(vectors[0])
    if expected_dimension is not None and dimension != expected_dimension:
        raise ValueError(f"embedding dimension mismatch: {dimension} != {expected_dimension}")
    for vector in vectors:
        if len(vector) != dimension:
            raise ValueError("inconsistent embedding dimensions")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding contains non-finite values")
        if not any(value != 0 for value in vector):
            raise ValueError("embedding vector is all zeros")
    return dimension
