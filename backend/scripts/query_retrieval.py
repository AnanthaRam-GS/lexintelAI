"""Diagnostic CLI for dense, BM25, and hybrid retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
from backend.app.services.reranking.base import RerankerConfig
from backend.app.services.reranking.bge import BgeReranker
from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_INDEX_NAME
from backend.app.services.retrieval.service import HybridConfig, RetrievalMode, RetrievalResponse, RetrievalService
from backend.app.services.vector_store import ChromaVectorStore
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR, REPO_ROOT, collection_metadata


SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/trusted_judgment_retrieval_summary.json"
RERANKING_SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/trusted_judgment_reranking_summary.json"
QA_PATH = REPO_ROOT / "docs/HYBRID_RETRIEVAL_QA.md"
RERANKING_QA_PATH = REPO_ROOT / "docs/RERANKING_QA.md"
DOC_PATH = REPO_ROOT / "docs/LEXICAL_AND_HYBRID_RETRIEVAL.md"
RERANKING_DOC_PATH = REPO_ROOT / "docs/RERANKING_FOUNDATION.md"
QUERIES = [
    "dowry death section 304B IPC",
    "murder conviction section 302 IPC",
    "criminal breach of trust section 406 IPC",
    "NDPS bail commercial quantity",
    "anticipatory bail under BNSS",
    "rape section 376 IPC",
    "robbery section 392 IPC",
    "common intention section 34 IPC",
]


def make_service(args: argparse.Namespace) -> RetrievalService:
    lexical_index = Bm25LexicalIndex(args.bm25_persist_dir, args.index_name, Bm25Config(k1=args.k1, b=args.b))
    dense_provider = None
    vector_store = None
    if args.mode in {"dense", "hybrid"} or args.qa or args.rerank_qa or args.smoke_reranker:
        config = EmbeddingConfig(model_name=args.embedding_model, device=args.device, batch_size=args.batch_size, normalize_embeddings=True)
        dense_provider = BgeM3EmbeddingProvider(config)
        vector_store = ChromaVectorStore(args.chroma_persist_dir, args.collection, collection_metadata(config, "real_bge_m3"))
    reranker = None
    if args.rerank or args.rerank_qa or args.smoke_reranker:
        reranker = BgeReranker(
            RerankerConfig(
                model_name=args.reranker_model,
                device=args.reranker_device,
                batch_size=args.reranker_batch_size,
                max_length=args.reranker_max_length,
                top_k=args.reranker_top_k,
            )
        )
    return RetrievalService(
        dense_provider=dense_provider,
        vector_store=vector_store,
        lexical_index=lexical_index,
        hybrid_config=HybridConfig(rrf_k=args.rrf_k, candidate_k=args.candidate_k),
        reranker=reranker,
    )


def compact_result(result: Any) -> dict[str, Any]:
    page = f"{result.page_start}-{result.page_end}" if result.page_start is not None else ""
    return {
        "rank": result.rank,
        "chunk_id": result.chunk_id,
        "case_title": result.case_title,
        "family": result.effective_offence_family,
        "regime": result.effective_legal_regime,
        "page": page,
        "score": round(result.score, 6),
        "dense_rank": result.dense_rank,
        "dense_score": round(result.dense_score, 6) if result.dense_score is not None else None,
        "lexical_rank": result.lexical_rank,
        "lexical_score": round(result.lexical_score, 6) if result.lexical_score is not None else None,
        "hybrid_score": round(result.hybrid_score, 6) if result.hybrid_score is not None else None,
        "rerank_rank": result.rerank_rank,
        "rerank_score": round(result.rerank_score, 6) if result.rerank_score is not None else None,
        "pre_rerank_rank": result.pre_rerank_rank,
        "pre_rerank_score": round(result.pre_rerank_score, 6) if result.pre_rerank_score is not None else None,
    }


def filters_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    filters = {
        "effective_offence_family": args.family,
        "effective_legal_regime": args.regime,
        "court": args.court,
    }
    return {key: value for key, value in filters.items() if value} or None


def overlap(left: list[Any], right: list[Any]) -> int:
    return len({result.chunk_id for result in left} & {result.chunk_id for result in right})


def run_single(service: RetrievalService, args: argparse.Namespace) -> RetrievalResponse:
    return service.retrieve(args.query, RetrievalMode(args.mode), top_k=args.top_k, candidate_k=args.candidate_k, filters=filters_from_args(args), rerank=args.rerank)


def run_qa(service: RetrievalService, args: argparse.Namespace) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    timings = {"dense": [], "lexical": [], "hybrid": []}
    for query in QUERIES:
        dense = service.retrieve(query, "dense", top_k=args.top_k, candidate_k=args.candidate_k)
        lexical = service.retrieve(query, "lexical", top_k=args.top_k, candidate_k=args.candidate_k)
        hybrid = service.retrieve(query, "hybrid", top_k=args.top_k, candidate_k=args.candidate_k)
        timings["dense"].append(dense.trace.total_latency_ms)
        timings["lexical"].append(lexical.trace.total_latency_ms)
        timings["hybrid"].append(hybrid.trace.total_latency_ms)
        rows.append(
            {
                "query": query,
                "dense": [compact_result(result) for result in dense.results],
                "lexical": [compact_result(result) for result in lexical.results],
                "hybrid": [compact_result(result) for result in hybrid.results],
                "overlap": {
                    "dense_bm25": overlap(dense.results, lexical.results),
                    "dense_hybrid": overlap(dense.results, hybrid.results),
                    "bm25_hybrid": overlap(lexical.results, hybrid.results),
                },
            }
        )
    summary = build_summary(service, args, rows, timings)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_qa(args, rows, summary)
    write_docs(args, summary)
    return summary


def run_reranker_smoke(service: RetrievalService, args: argparse.Namespace) -> dict[str, Any]:
    response = service.retrieve("murder conviction section 302 IPC", "hybrid", top_k=3, candidate_k=5, rerank=True)
    scores = [result.rerank_score for result in response.results]
    return {
        "model": args.reranker_model,
        "device": args.reranker_device,
        "batch_size": args.reranker_batch_size,
        "max_length": args.reranker_max_length,
        "candidate_count": 5,
        "result_count": len(response.results),
        "scores_finite": all(score is not None for score in scores),
        "higher_is_better": True,
        "results": [compact_result(result) for result in response.results],
    }


def run_rerank_qa(service: RetrievalService, args: argparse.Namespace) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rerank_times: list[float] = []
    total_times: list[float] = []
    rank1_changed = 0
    top5_changed = 0
    failures = 0
    for query in QUERIES:
        try:
            hybrid = service.retrieve(query, "hybrid", top_k=args.top_k, candidate_k=args.candidate_k)
            reranked = service.retrieve(query, "hybrid", top_k=args.top_k, candidate_k=args.candidate_k, rerank=True)
            rerank_times.append(reranked.trace.rerank_latency_ms)
            total_times.append(reranked.trace.total_latency_ms)
            if hybrid.results and reranked.results and hybrid.results[0].chunk_id != reranked.results[0].chunk_id:
                rank1_changed += 1
            if {result.chunk_id for result in hybrid.results} != {result.chunk_id for result in reranked.results}:
                top5_changed += 1
            rows.append(
                {
                    "query": query,
                    "hybrid": [compact_result(result) for result in hybrid.results],
                    "reranked": [compact_result(result) for result in reranked.results],
                }
            )
        except Exception as exc:
            failures += 1
            rows.append({"query": query, "failure": f"{type(exc).__name__}: {exc}", "hybrid": [], "reranked": []})
    reranker_config = RerankerConfig(max_length=args.reranker_max_length)
    summary = {
        "reranking_version": "legalai-reranking-foundation-v1",
        "model": args.reranker_model,
        "library": "FlagEmbedding",
        "device": args.reranker_device,
        "candidate_k": args.candidate_k,
        "top_k": args.top_k,
        "max_length": args.reranker_max_length,
        "batch_size": args.reranker_batch_size,
        "truncation_policy": reranker_config.truncation_policy,
        "query_count": len(QUERIES),
        "success_count": len(QUERIES) - failures,
        "failure_count": failures,
        "timing": {
            "median_rerank_ms": timing_summary(rerank_times)["median_ms"] if rerank_times else 0,
            "p95_rerank_ms": timing_summary(rerank_times)["p95_ms"] if rerank_times else 0,
            "median_total_ms": timing_summary(total_times)["median_ms"] if total_times else 0,
            "p95_total_ms": timing_summary(total_times)["p95_ms"] if total_times else 0,
        },
        "diagnostic_movement": {
            "rank_1_changed_count": rank1_changed,
            "top_5_membership_changed_count": top5_changed,
        },
    }
    RERANKING_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_reranking_qa(args, rows, summary)
    write_reranking_docs(summary)
    return summary


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * pct)))
    return ordered[index]


def timing_summary(values: list[float]) -> dict[str, float]:
    return {"median_ms": round(statistics.median(values), 3), "p95_ms": round(percentile(values, 0.95), 3)}


def build_summary(service: RetrievalService, args: argparse.Namespace, rows: list[dict[str, Any]], timings: dict[str, list[float]]) -> dict[str, Any]:
    return {
        "retrieval_version": "legalai-retrieval-foundation-v1",
        "chunk_count": service.lexical_index.count() if service.lexical_index else 0,
        "dense": {
            "model": args.embedding_model,
            "collection": args.collection,
            "index_version": "legalai-chroma-index-v1",
            "count": service.vector_store.count() if service.vector_store else 0,
        },
        "lexical": {
            "index_version": service.lexical_index.metadata.get("index_version") if service.lexical_index else None,
            "tokenizer_version": service.lexical_index.metadata.get("tokenizer_version") if service.lexical_index else None,
            "k1": args.k1,
            "b": args.b,
            "count": service.lexical_index.count() if service.lexical_index else 0,
        },
        "hybrid": {"fusion": "reciprocal_rank_fusion", "rrf_k": args.rrf_k, "candidate_k": args.candidate_k},
        "top_k": args.top_k,
        "sanity_query_count": len(rows),
        "timing_summary": {mode: timing_summary(values) for mode, values in timings.items()},
    }


def top_label(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    first = items[0]
    return f"{first['chunk_id']} ({first['family']}/{first['regime']})"


def write_qa(args: argparse.Namespace, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Hybrid Retrieval QA",
        "",
        "This is a diagnostic sanity comparison, not a formal retrieval benchmark.",
        "",
        "## Configuration",
        "",
        f"- dense model: `{args.embedding_model}`",
        f"- BM25: k1={args.k1}, b={args.b}",
        f"- tokenizer: `{summary['lexical']['tokenizer_version']}`",
        f"- RRF K: {args.rrf_k}",
        f"- candidate_k: {args.candidate_k}",
        f"- top_k: {args.top_k}",
        "",
        "## Rank 1 Comparison",
        "",
        "| Query | Dense Rank 1 | BM25 Rank 1 | Hybrid Rank 1 |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| {row['query']} | {top_label(row['dense'])} | {top_label(row['lexical'])} | {top_label(row['hybrid'])} |")
    lines.extend(["", "## Top 5 Details", ""])
    for row in rows:
        lines.extend([f"### {row['query']}", "", f"Overlap dense/BM25={row['overlap']['dense_bm25']}, dense/hybrid={row['overlap']['dense_hybrid']}, BM25/hybrid={row['overlap']['bm25_hybrid']}.", ""])
        for mode in ["dense", "lexical", "hybrid"]:
            lines.append(f"**{mode}**")
            for result in row[mode]:
                lines.append(f"- {result['rank']}. `{result['chunk_id']}` {result['family']}/{result['regime']} page {result['page']} score {result['score']}")
            lines.append("")
    QA_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_docs(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    lines = [
        "# Lexical And Hybrid Retrieval",
        "",
        "This phase adds deterministic BM25 lexical retrieval and Reciprocal Rank Fusion over the existing real BGE-M3 Chroma dense index.",
        "",
        "## Scope",
        "",
        f"- documents: 70",
        f"- chunks: {summary['chunk_count']}",
        "- trusted 0.5A chunks only",
        "",
        "## BM25",
        "",
        f"- implementation: internal local BM25",
        f"- index version: `{summary['lexical']['index_version']}`",
        f"- tokenizer version: `{summary['lexical']['tokenizer_version']}`",
        f"- k1: {args.k1}",
        f"- b: {args.b}",
        "- no generic English stopword list is applied",
        "- statute normalization preserves legal tokens and adds safe alternates such as `304-B`/`304B` and `498-A`/`498A`",
        "",
        "## Dense Reuse",
        "",
        "Dense retrieval reuses the existing BGE-M3 embedding provider and Chroma vector-store abstraction. It does not create a second dense index path.",
        "",
        "## Hybrid",
        "",
        f"Hybrid retrieval uses Reciprocal Rank Fusion with RRF_K={args.rrf_k}. Each retriever contributes up to candidate_k={args.candidate_k}; duplicates are fused by `chunk_id`.",
        "",
        "## Score Semantics",
        "",
        "Dense scores are Chroma cosine similarities derived from `1 - distance`. BM25 scores are lexical relevance scores. Hybrid scores are RRF scores. These scores are diagnostic and not directly interchangeable.",
        "",
        "## Filters",
        "",
        "The retrieval service accepts optional `effective_legal_regime`, `effective_offence_family`, and `court` filters. Filters are infrastructure only and are not query-derived.",
        "",
        "## CLI",
        "",
        "```bash",
        "python3 backend/scripts/build_lexical_index.py --dry-run",
        "python3 backend/scripts/build_lexical_index.py --rebuild",
        "HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --query \"murder section 302 IPC\" --mode hybrid --top-k 5 --candidate-k 20",
        "HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --qa",
        "```",
        "",
        "No reranker, LLM/RAG generation, Gemini, Ollama, InLegalBERT, query NLP/NER, or formal retrieval benchmark is implemented in this phase.",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reranking_qa(args: argparse.Namespace, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Reranking QA",
        "",
        "This is diagnostic sanity QA for a BGE reranker over retrieved candidates, not a formal retrieval benchmark.",
        "",
        "## Configuration",
        "",
        f"- model: `{args.reranker_model}`",
        "- library: `FlagEmbedding`",
        f"- device: `{args.reranker_device}`",
        f"- candidate_k: {args.candidate_k}",
        f"- top_k: {args.top_k}",
        f"- max_length: {args.reranker_max_length}",
        f"- batch_size: {args.reranker_batch_size}",
        f"- truncation policy: {summary['truncation_policy']}",
        "",
        "## Rank 1 Movement",
        "",
        "| Query | Hybrid Rank 1 | Reranked Rank 1 | Changed |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        hybrid_top = top_label(row.get("hybrid", []))
        reranked_top = top_label(row.get("reranked", []))
        lines.append(f"| {row['query']} | {hybrid_top} | {reranked_top} | {hybrid_top != reranked_top} |")
    lines.extend(["", "## Details", ""])
    for row in rows:
        lines.extend([f"### {row['query']}", ""])
        if row.get("failure"):
            lines.extend([f"Failure: {row['failure']}", ""])
            continue
        lines.append("**pre-rerank hybrid**")
        for result in row["hybrid"]:
            lines.append(f"- {result['rank']}. `{result['chunk_id']}` {result['family']}/{result['regime']} page {result['page']} score {result['score']}")
        lines.append("")
        lines.append("**post-rerank**")
        for result in row["reranked"]:
            lines.append(f"- {result['rank']}. `{result['chunk_id']}` {result['family']}/{result['regime']} page {result['page']} pre-rank {result['pre_rerank_rank']} rerank {result['rerank_score']}")
        lines.append("")
    RERANKING_QA_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_reranking_docs(summary: dict[str, Any]) -> None:
    lines = [
        "# Reranking Foundation",
        "",
        "This phase adds a BGE reranking layer over existing dense, lexical, or hybrid retrieval candidates. It does not generate answers or perform formal retrieval evaluation.",
        "",
        "## Reranker Choice",
        "",
        f"- model: `{summary['model']}`",
        "- library: `FlagEmbedding`",
        f"- device: `{summary['device']}`",
        f"- batch size: {summary['batch_size']}",
        f"- max length: {summary['max_length']}",
        "",
        "## Candidate Flow",
        "",
        f"Default diagnostic flow retrieves hybrid candidates with candidate_k={summary['candidate_k']} and reranks to top_k={summary['top_k']}. Dense-only and lexical-only reranking are also supported by the same service.",
        "",
        "## Score Semantics",
        "",
        "The BGE reranker returns model scores for query-passage pairs. They are recorded as `rerank_score`; higher values are treated as better. They are not probabilities or cosine similarities.",
        "",
        "## Preservation",
        "",
        "Reranking preserves original dense, lexical, and hybrid ranks/scores and all chunk provenance. Final `rank` is the post-rerank position.",
        "",
        "## Truncation And Batching",
        "",
        summary["truncation_policy"],
        "",
        "Candidate pairs are scored in configurable batches to avoid one model invocation per candidate.",
        "",
        "## CLI",
        "",
        "```bash",
        "HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --query \"murder conviction section 302 IPC\" --mode hybrid --candidate-k 20 --top-k 5 --rerank",
        "HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --smoke-reranker",
        "HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --rerank-qa",
        "```",
        "",
        "No Gemini, Ollama, answer generation, RAG orchestration, query NLP/NER enrichment, InLegalBERT, or formal metrics are implemented here.",
    ]
    RERANKING_DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="")
    parser.add_argument("--mode", choices=[mode.value for mode in RetrievalMode], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--family")
    parser.add_argument("--regime")
    parser.add_argument("--court")
    parser.add_argument("--bm25-persist-dir", type=Path, default=BM25_PERSIST_DIR)
    parser.add_argument("--chroma-persist-dir", type=Path, default=CHROMA_PERSIST_DIR)
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--qa", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-qa", action="store_true")
    parser.add_argument("--smoke-reranker", action="store_true")
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-max-length", type=int, default=512)
    parser.add_argument("--reranker-top-k", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = make_service(args)
    if args.smoke_reranker:
        print(json.dumps(run_reranker_smoke(service, args), indent=2, ensure_ascii=False))
        return 0
    if args.rerank_qa:
        print(json.dumps(run_rerank_qa(service, args), indent=2, ensure_ascii=False))
        return 0
    if args.qa:
        print(json.dumps(run_qa(service, args), indent=2, ensure_ascii=False))
        return 0
    if not args.query:
        raise SystemExit("--query is required unless --qa is used")
    response = run_single(service, args)
    print(json.dumps({"trace": response.trace.__dict__, "results": [compact_result(result) for result in response.results]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
