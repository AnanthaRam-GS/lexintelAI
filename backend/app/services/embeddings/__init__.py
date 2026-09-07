"""Embedding service abstractions for LegalAI."""

from backend.app.services.embeddings.base import EmbeddingConfig, EmbeddingProvider
from backend.app.services.embeddings.mock import DeterministicMockEmbeddingProvider

__all__ = ["EmbeddingConfig", "EmbeddingProvider", "DeterministicMockEmbeddingProvider"]
