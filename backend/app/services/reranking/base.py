"""Shared reranker contracts."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.services.vector_store import RetrievalResult


@dataclass(frozen=True)
class RerankerConfig:
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cpu"
    batch_size: int = 8
    max_length: int = 512
    top_k: int = 5
    use_fp16: bool = False
    truncation_policy: str = "FlagEmbedding pair tokenizer truncates deterministically to max_length, preserving the query and passage prefix per model tokenizer behavior."


class Reranker:
    config: RerankerConfig

    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        raise NotImplementedError

    def rerank(self, query: str, candidates: list[RetrievalResult], top_k: int | None = None) -> list[RetrievalResult]:
        if not candidates:
            return []
        scores = self.score_pairs(query, candidates)
        if len(scores) != len(candidates):
            raise ValueError("reranker returned a score count that does not match candidates")
        ranked = sorted(
            ((score, index, candidate) for index, (score, candidate) in enumerate(zip(scores, candidates))),
            key=lambda item: (-item[0], item[1], item[2].chunk_id),
        )
        limit = top_k if top_k is not None else self.config.top_k
        return [
            clone_reranked_result(candidate, score=score, rerank_rank=rank)
            for rank, (score, _index, candidate) in enumerate(ranked[:limit], start=1)
        ]


def clone_reranked_result(candidate: RetrievalResult, score: float, rerank_rank: int) -> RetrievalResult:
    values = candidate.__dict__ | {
        "rank": rerank_rank,
        "score": score,
        "rerank_score": score,
        "rerank_rank": rerank_rank,
        "pre_rerank_rank": candidate.rank,
        "pre_rerank_score": candidate.score,
    }
    return RetrievalResult(**values)
