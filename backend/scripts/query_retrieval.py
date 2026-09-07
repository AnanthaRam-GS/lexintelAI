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
from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_INDEX_NAME
from backend.app.services.retrieval.service import HybridConfig, RetrievalMode, RetrievalResponse, RetrievalService
from backend.app.services.vector_store import ChromaVectorStore
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR, REPO_ROOT, collection_metadata


SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/trusted_judgment_retrieval_summary.json"
QA_PATH = REPO_ROOT / "docs/HYBRID_RETRIEVAL_QA.md"
DOC_PATH = REPO_ROOT / "docs/LEXICAL_AND_HYBRID_RETRIEVAL.md"
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
    if args.mode in {"dense", "hybrid"} or args.qa:
        config = EmbeddingConfig(model_name=args.embedding_model, device=args.device, batch_size=args.batch_size, normalize_embeddings=True)
        dense_provider = BgeM3EmbeddingProvider(config)
        vector_store = ChromaVectorStore(args.chroma_persist_dir, args.collection, collection_metadata(config, "real_bge_m3"))
    return RetrievalService(
        dense_provider=dense_provider,
        vector_store=vector_store,
        lexical_index=lexical_index,
        hybrid_config=HybridConfig(rrf_k=args.rrf_k, candidate_k=args.candidate_k),
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
    return service.retrieve(args.query, RetrievalMode(args.mode), top_k=args.top_k, candidate_k=args.candidate_k, filters=filters_from_args(args))


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = make_service(args)
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
