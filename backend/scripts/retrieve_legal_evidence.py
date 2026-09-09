"""Retrieve citation-ready LegalAI evidence without answer generation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.app.services.reranking.base import RerankerConfig
from backend.app.services.reranking.bge import BgeReranker
from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_INDEX_NAME
from backend.app.services.retrieval.service import HybridConfig, RetrievalService
from backend.app.services.vector_store import ChromaVectorStore
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR, collection_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Raw legal query text")
    parser.add_argument("--include-text", action="store_true", help="Include full chunk text in output")
    parser.add_argument("--bm25-persist-dir", type=Path, default=BM25_PERSIST_DIR)
    parser.add_argument("--chroma-persist-dir", type=Path, default=CHROMA_PERSIST_DIR)
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    return parser


def make_service(args: argparse.Namespace) -> RetrievalService:
    embedding_config = EmbeddingConfig(model_name="BAAI/bge-m3", device="cpu", batch_size=8, normalize_embeddings=True)
    return RetrievalService(
        dense_provider=BgeM3EmbeddingProvider(embedding_config),
        vector_store=ChromaVectorStore(args.chroma_persist_dir, args.collection, collection_metadata(embedding_config, "real_bge_m3")),
        lexical_index=Bm25LexicalIndex(args.bm25_persist_dir, args.index_name, Bm25Config(k1=1.5, b=0.75)),
        hybrid_config=HybridConfig(rrf_k=60, candidate_k=20),
        reranker=BgeReranker(
            RerankerConfig(
                model_name="BAAI/bge-reranker-v2-m3",
                device="cpu",
                batch_size=8,
                max_length=512,
                top_k=5,
            )
        ),
    )


def compact_payload(payload: dict, include_text: bool) -> dict:
    if include_text:
        return payload
    compact = dict(payload)
    compact["evidence"] = [
        {key: value for key, value in item.items() if key != "text"}
        for item in payload.get("evidence", [])
    ]
    return compact


def main() -> int:
    args = build_parser().parse_args()
    understanding = understand_legal_query(args.query, section_ranking_mode="deterministic")
    service = make_service(args)
    result = retrieve_legal_evidence(understanding, retrieval_service=service)
    print(json.dumps(compact_payload(result.model_dump(mode="json"), args.include_text), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
