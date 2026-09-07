"""Shared dense, lexical, and hybrid retrieval service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import time
from typing import Any

from backend.app.services.embeddings.base import EmbeddingProvider
from backend.app.services.reranking.base import Reranker
from backend.app.services.retrieval.bm25 import Bm25LexicalIndex
from backend.app.services.vector_store import ChromaVectorStore, RetrievalResult, result_matches_filters


class RetrievalMode(StrEnum):
    DENSE = "dense"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    mode: str
    candidate_k: int
    top_k: int
    dense_latency_ms: float
    dense_embedding_latency_ms: float
    dense_query_latency_ms: float
    lexical_latency_ms: float
    fusion_latency_ms: float
    rerank_latency_ms: float
    total_latency_ms: float
    dense_candidate_count: int
    lexical_candidate_count: int
    fused_candidate_count: int
    filters: dict[str, Any] | None
    rerank: bool = False


@dataclass(frozen=True)
class RetrievalResponse:
    results: list[RetrievalResult]
    trace: RetrievalTrace


@dataclass(frozen=True)
class HybridConfig:
    rrf_k: int = 60
    candidate_k: int = 20


class RetrievalService:
    def __init__(
        self,
        dense_provider: EmbeddingProvider | None = None,
        vector_store: ChromaVectorStore | None = None,
        lexical_index: Bm25LexicalIndex | None = None,
        hybrid_config: HybridConfig | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.dense_provider = dense_provider
        self.vector_store = vector_store
        self.lexical_index = lexical_index
        self.hybrid_config = hybrid_config or HybridConfig()
        self.reranker = reranker

    def retrieve(
        self,
        query: str,
        mode: RetrievalMode | str = RetrievalMode.HYBRID,
        top_k: int = 5,
        candidate_k: int | None = None,
        filters: dict[str, Any] | None = None,
        rerank: bool = False,
    ) -> RetrievalResponse:
        started = time.monotonic()
        retrieval_mode = RetrievalMode(mode)
        depth = candidate_k or self.hybrid_config.candidate_k
        dense_results: list[RetrievalResult] = []
        lexical_results: list[RetrievalResult] = []
        dense_embedding_ms = dense_query_ms = lexical_ms = fusion_ms = rerank_ms = 0.0
        retrieval_depth = depth if retrieval_mode == RetrievalMode.HYBRID or rerank else top_k
        if retrieval_mode in {RetrievalMode.DENSE, RetrievalMode.HYBRID}:
            dense_results, dense_embedding_ms, dense_query_ms = self._dense(query, retrieval_depth, filters)
        if retrieval_mode in {RetrievalMode.LEXICAL, RetrievalMode.HYBRID}:
            lexical_started = time.monotonic()
            lexical_results = self._lexical(query, retrieval_depth, filters)
            lexical_ms = elapsed_ms(lexical_started)
        if retrieval_mode == RetrievalMode.DENSE:
            results = mark_dense(dense_results)
        elif retrieval_mode == RetrievalMode.LEXICAL:
            results = lexical_results
        else:
            fusion_started = time.monotonic()
            results = reciprocal_rank_fusion(dense_results, lexical_results, self.hybrid_config.rrf_k)[:retrieval_depth]
            fusion_ms = elapsed_ms(fusion_started)
        results = [set_rank(result, rank) for rank, result in enumerate(results, start=1)]
        if rerank:
            if self.reranker is None:
                raise RuntimeError("reranker is required when rerank=True")
            rerank_started = time.monotonic()
            results = self.reranker.rerank(query, results, top_k=top_k)
            rerank_ms = elapsed_ms(rerank_started)
        else:
            results = results[:top_k]
        results = [set_rank(result, rank) for rank, result in enumerate(results, start=1)]
        total_ms = elapsed_ms(started)
        trace = RetrievalTrace(
            query=query,
            mode=retrieval_mode.value,
            candidate_k=depth,
            top_k=top_k,
            dense_latency_ms=dense_embedding_ms + dense_query_ms,
            dense_embedding_latency_ms=dense_embedding_ms,
            dense_query_latency_ms=dense_query_ms,
            lexical_latency_ms=lexical_ms,
            fusion_latency_ms=fusion_ms,
            rerank_latency_ms=rerank_ms,
            total_latency_ms=total_ms,
            dense_candidate_count=len(dense_results),
            lexical_candidate_count=len(lexical_results),
            fused_candidate_count=len(results),
            filters=filters,
            rerank=rerank,
        )
        return RetrievalResponse(results=results, trace=trace)

    def _dense(self, query: str, top_k: int, filters: dict[str, Any] | None) -> tuple[list[RetrievalResult], float, float]:
        if self.dense_provider is None or self.vector_store is None:
            raise RuntimeError("dense provider and vector store are required for dense retrieval")
        embedding_started = time.monotonic()
        vector = self.dense_provider.embed_query(query)
        embedding_ms = elapsed_ms(embedding_started)
        query_started = time.monotonic()
        depth = top_k * 5 if filters and filters.get("court") else top_k
        results = filter_results(self.vector_store.query_dense(vector, top_k=depth, filters=filters), filters)[:top_k]
        query_ms = elapsed_ms(query_started)
        return mark_dense(results), embedding_ms, query_ms

    def _lexical(self, query: str, top_k: int, filters: dict[str, Any] | None) -> list[RetrievalResult]:
        if self.lexical_index is None:
            raise RuntimeError("lexical index is required for lexical retrieval")
        return self.lexical_index.query(query, top_k=top_k, filters=filters)


def elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000


def mark_dense(results: list[RetrievalResult]) -> list[RetrievalResult]:
    return [
        clone_result(result, retrieval_mode="dense", dense_rank=result.rank, dense_score=result.score)
        for result in results
    ]


def reciprocal_rank_fusion(dense_results: list[RetrievalResult], lexical_results: list[RetrievalResult], rrf_k: int = 60) -> list[RetrievalResult]:
    fused: dict[str, RetrievalResult] = {}
    scores: dict[str, float] = {}
    for result in dense_results:
        fused[result.chunk_id] = clone_result(result, retrieval_mode="hybrid", dense_rank=result.rank, dense_score=result.score)
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (rrf_k + result.rank)
    for result in lexical_results:
        previous = fused.get(result.chunk_id)
        base = previous or result
        fused[result.chunk_id] = clone_result(
            base,
            retrieval_mode="hybrid",
            dense_rank=previous.dense_rank if previous else None,
            dense_score=previous.dense_score if previous else None,
            lexical_rank=result.rank,
            lexical_score=result.score,
        )
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (rrf_k + result.rank)
    ordered = sorted(fused.values(), key=lambda item: (-scores[item.chunk_id], item.chunk_id))
    return [clone_result(result, score=scores[result.chunk_id], hybrid_score=scores[result.chunk_id]) for result in ordered]


def set_rank(result: RetrievalResult, rank: int) -> RetrievalResult:
    return clone_result(result, rank=rank)


def clone_result(result: RetrievalResult, **updates: Any) -> RetrievalResult:
    values = result.__dict__ | updates
    return RetrievalResult(**values)


def filter_results(results: list[RetrievalResult], filters: dict[str, Any] | None) -> list[RetrievalResult]:
    return [result for result in results if result_matches_filters(result, filters)]
