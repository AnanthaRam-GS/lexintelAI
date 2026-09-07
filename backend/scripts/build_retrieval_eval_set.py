"""Build the human-labelled retrieval evaluation packet and candidate pools."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
from backend.app.services.reranking.base import RerankerConfig
from backend.app.services.reranking.bge import BgeReranker
from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_INDEX_NAME, LEXICAL_INDEX_VERSION, TOKENIZER_VERSION
from backend.app.services.retrieval.evaluation import EVALUATION_VERSION, POOLING_VERSION, PoolingConfig, build_query_manifest, generate_pool, workload_summary
from backend.app.services.retrieval.service import HybridConfig, RetrievalService
from backend.app.services.vector_store import ChromaVectorStore
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR, REPO_ROOT, collection_metadata, load_chunks


QUERIES_PATH = REPO_ROOT / "data/structured/manifests/retrieval_eval_queries.json"
JUDGMENTS_PATH = REPO_ROOT / "data/structured/manifests/retrieval_eval_judgments.json"
TRACES_PATH = REPO_ROOT / "data/structured/manifests/retrieval_eval_pool_traces.json"
SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/retrieval_eval_summary.json"
REVIEW_DOC = REPO_ROOT / "docs/RETRIEVAL_EVALUATION_REVIEW.md"
METHODOLOGY_DOC = REPO_ROOT / "docs/RETRIEVAL_EVALUATION_METHODOLOGY.md"


class RealRetriever:
    def __init__(self, service: RetrievalService) -> None:
        self.service = service

    def retrieve(self, query: str, mode: str, top_k: int, candidate_k: int, rerank: bool = False) -> list[Any]:
        return self.service.retrieve(query, mode, top_k=top_k, candidate_k=candidate_k, rerank=rerank).results


def make_service(args: argparse.Namespace) -> RetrievalService:
    embedding_config = EmbeddingConfig(model_name=args.embedding_model, device=args.device, batch_size=args.embedding_batch_size, normalize_embeddings=True)
    return RetrievalService(
        dense_provider=BgeM3EmbeddingProvider(embedding_config),
        vector_store=ChromaVectorStore(args.chroma_persist_dir, args.collection, collection_metadata(embedding_config, "real_bge_m3")),
        lexical_index=Bm25LexicalIndex(args.bm25_persist_dir, args.index_name, Bm25Config(k1=args.k1, b=args.b)),
        hybrid_config=HybridConfig(rrf_k=args.rrf_k, candidate_k=args.candidate_depth),
        reranker=BgeReranker(RerankerConfig(model_name=args.reranker_model, device=args.device, batch_size=args.reranker_batch_size, max_length=args.reranker_max_length, top_k=args.top_k)),
    )


def write_review_doc(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in judgments:
        by_query.setdefault(row["query_id"], []).append(row)
    lines = [
        "# Retrieval Evaluation Review Packet",
        "",
        "This packet is blinded: retriever ranks and scores are stored separately and are not shown here.",
        "",
        f"- evaluation version: `{EVALUATION_VERSION}`",
        f"- pooling version: `{POOLING_VERSION}`",
        f"- query count: {summary['workload']['query_count']}",
        f"- pooled chunks: {summary['workload']['total_pooled_chunks']}",
        "",
        "Relevance scale: 2 highly relevant, 1 partially relevant, 0 not relevant, uncertain if the reviewer cannot decide confidently.",
        "",
    ]
    for query in queries:
        lines.extend([
            f"## {query['query_id']}: {query['query_text']}",
            "",
            f"- type: `{query['query_type']}`",
            f"- target family: `{query['target_family']}`",
            f"- target regime: `{query['target_regime']}`",
            f"- difficulty: `{query['difficulty']}`",
            "",
        ])
        for row in sorted(by_query.get(query["query_id"], []), key=lambda item: item["blinded_order"]):
            page = f"{row['page_start']}-{row['page_end']}" if row["page_start"] is not None else ""
            court = row.get("court") or {}
            lines.extend([
                f"### Candidate {row['blinded_order']}: `{row['chunk_id']}`",
                "",
                f"- judgment: {row['case_title']}",
                f"- court: {court.get('court_name', '')}",
                f"- date: {row.get('decision_date') or ''}",
                f"- page/paragraph: {page} / {row['paragraph_start']}-{row['paragraph_end']}",
                f"- family/regime: `{row['effective_offence_family']}` / `{row['effective_legal_regime']}`",
                "",
                row["bounded_chunk_preview"],
                "",
                "- [ ] relevance: 2 / 1 / 0 / uncertain",
                "- [ ] document relevant: yes / no / uncertain",
                "- [ ] notes:",
                "",
            ])
    REVIEW_DOC.write_text("\n".join(lines), encoding="utf-8")


def write_methodology_doc(summary: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Evaluation Methodology",
        "",
        "Human labels are required because prior sanity queries are diagnostic only and cannot support formal retrieval metrics.",
        "",
        "## Corpus",
        "",
        "The benchmark uses only the trusted 70-judgment, 1356-chunk corpus.",
        "",
        "## Query Design",
        "",
        "The query set contains exactly 30 corpus-supported queries across statute-explicit, plain-language, procedural/relief, transition/regime, and hard ambiguous categories.",
        "",
        "## Candidate Pooling",
        "",
        f"Pooling version `{POOLING_VERSION}` uses BM25, dense BGE-M3, hybrid RRF, and hybrid plus BGE reranker. It retrieves depth {summary['pooling_policy']['candidate_depth']} and caps blinded pools at {summary['pooling_policy']['max_pool_size']} candidates per query while retaining each system top {summary['pooling_policy']['always_retain_top']}.",
        "",
        "## Blinding",
        "",
        "The human review packet omits retriever ranks and scores. Machine traces are stored separately.",
        "",
        "## Relevance Grades",
        "",
        "2 means directly/highly relevant. 1 means partially useful. 0 means not materially relevant. uncertain is separate and is not automatically relevant.",
        "",
        "## Chunk And Document Relevance",
        "",
        "Reviewers judge chunk relevance and separately mark whether the document is relevant, allowing right-judgment/wrong-chunk cases.",
        "",
        "## Future Metrics",
        "",
        "Step 0.5E-L2 may compute Precision@5, pooled Recall@5, pooled Recall@20, MRR, and nDCG@5 after labels exist. Recall is pooled recall unless exhaustive corpus relevance is established.",
        "",
        "## Frozen Configuration",
        "",
        f"- dense: `{summary['frozen_retrieval_config']['dense_model']}`",
        f"- BM25: k1={summary['frozen_retrieval_config']['bm25_k1']}, b={summary['frozen_retrieval_config']['bm25_b']}",
        f"- hybrid RRF K: {summary['frozen_retrieval_config']['rrf_k']}",
        f"- reranker: `{summary['frozen_retrieval_config']['reranker_model']}`",
        "",
        "No Gemini, Ollama, external LLM, InLegalBERT, retrieval tuning, answer generation, or formal metric reporting is performed in this task.",
    ]
    METHODOLOGY_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_payload(args: argparse.Namespace, queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    workload = workload_summary(judgments)
    return {
        "evaluation_version": EVALUATION_VERSION,
        "pooling_version": POOLING_VERSION,
        "query_count": len(queries),
        "chunk_count": len(chunks),
        "document_count": len({chunk["document_id"] for chunk in chunks}),
        "query_type_distribution": dict(sorted(Counter(query["query_type"] for query in queries).items())),
        "family_distribution": dict(sorted(Counter(query["target_family"] for query in queries).items())),
        "regime_distribution": dict(sorted(Counter(query["target_regime"] for query in queries).items())),
        "workload": workload,
        "human_labels_assigned": 0,
        "trace_count": len(traces),
        "pooling_policy": {
            "candidate_depth": args.candidate_depth,
            "primary_depth": args.primary_depth,
            "always_retain_top": args.always_retain_top,
            "max_pool_size": args.max_pool_size,
        },
        "retrieval_versions": {
            "dense_index_version": "legalai-chroma-index-v1",
            "lexical_index_version": LEXICAL_INDEX_VERSION,
            "tokenizer_version": TOKENIZER_VERSION,
            "evaluation_trace_version": "legalai-retrieval-trace-v1",
        },
        "frozen_retrieval_config": {
            "dense_model": args.embedding_model,
            "bm25_k1": args.k1,
            "bm25_b": args.b,
            "rrf_k": args.rrf_k,
            "reranker_model": args.reranker_model,
            "candidate_depth": args.candidate_depth,
            "top_k": args.top_k,
        },
        "metric_status": "not_available_until_human_labels_exist",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate-depth", type=int, default=20)
    parser.add_argument("--primary-depth", type=int, default=15)
    parser.add_argument("--always-retain-top", type=int, default=5)
    parser.add_argument("--max-pool-size", type=int, default=25)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--bm25-persist-dir", type=Path, default=BM25_PERSIST_DIR)
    parser.add_argument("--chroma-persist-dir", type=Path, default=CHROMA_PERSIST_DIR)
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-max-length", type=int, default=512)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chunks = load_chunks()
    queries = build_query_manifest(chunks)
    if args.dry_run:
        payload = summary_payload(args, queries, [], [], chunks)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    service = make_service(args)
    judgments, traces = generate_pool(queries, RealRetriever(service), PoolingConfig(args.candidate_depth, args.primary_depth, args.always_retain_top, args.max_pool_size))
    summary = summary_payload(args, queries, judgments, traces, chunks)
    QUERIES_PATH.write_text(json.dumps(queries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    JUDGMENTS_PATH.write_text(json.dumps(judgments, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    TRACES_PATH.write_text(json.dumps(traces, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_review_doc(queries, judgments, summary)
    write_methodology_doc(summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
