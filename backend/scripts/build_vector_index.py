"""Build the dense vector index for trusted judgment chunks."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import importlib.metadata as importlib_metadata
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import DEFAULT_CHROMA_COLLECTION, Settings, resolve_chroma_location  # noqa: E402
from backend.app.services.embeddings.base import EmbeddingConfig, EmbeddingProvider, validate_vectors  # noqa: E402
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider  # noqa: E402
from backend.app.services.embeddings.mock import DeterministicMockEmbeddingProvider  # noqa: E402
from backend.app.services.vector_store import INDEX_VERSION, ChromaVectorStore, JsonVectorStore, metadata_for_chroma  # noqa: E402
from backend.scripts.env_utils import load_project_env  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
CHUNK_DIR = REPO_ROOT / "data/processed/judgment_chunks"
CHUNK_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_chunk_summary.json"
VECTOR_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_vector_index_summary.json"
VECTOR_QA = REPO_ROOT / "docs/VECTOR_INDEX_QA.md"
DOC_PATH = REPO_ROOT / "docs/EMBEDDING_AND_VECTOR_INDEX.md"
DEFAULT_COLLECTION = DEFAULT_CHROMA_COLLECTION
DEFAULT_PERSIST_DIR = REPO_ROOT / "chroma_store"
SEMANTIC_QUERIES = [
    "dowry death section 304B IPC",
    "murder conviction section 302 IPC",
    "criminal breach of trust section 406 IPC",
    "NDPS bail commercial quantity",
    "anticipatory bail under BNSS",
    "sexual offence rape section 376 IPC",
    "robbery section 392 IPC",
]


def bge_m3_available() -> bool:
    cache_candidates = [
        Path.home() / ".cache/huggingface/hub/models--BAAI--bge-m3",
        REPO_ROOT / "models/bge-m3",
    ]
    return importlib.util.find_spec("FlagEmbedding") is not None and any(path.exists() for path in cache_candidates)


def load_chunks(chunk_dir: Path = CHUNK_DIR, limit: int | None = None, document_id: str | None = None) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if document_id and row.get("document_id") != document_id:
                continue
            chunks.append(row)
            if limit is not None and len(chunks) >= limit:
                return chunks
    return chunks


def chunk_text_hash(chunk: dict[str, Any]) -> str:
    return hashlib.sha256(str(chunk.get("chunk_text") or "").encode("utf-8")).hexdigest()


def index_fingerprint(chunk: dict[str, Any], config: EmbeddingConfig) -> str:
    payload = {
        "chunk_id": chunk["chunk_id"],
        "chunk_text_hash": chunk_text_hash(chunk),
        "model": config.model_name,
        "dimension": config.dimension,
        "normalize": config.normalize_embeddings,
        "index_version": INDEX_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def provider_from_config(real: bool, config: EmbeddingConfig) -> tuple[EmbeddingProvider, str, bool]:
    if real:
        if not bge_m3_available():
            raise RuntimeError("BGE-M3 is not locally available; do not download silently")
        provider = BgeM3EmbeddingProvider(config)
        return provider, "real_bge_m3", True
    mock = DeterministicMockEmbeddingProvider(
        EmbeddingConfig(
            model_name="deterministic-mock",
            device=config.device,
            batch_size=config.batch_size,
            normalize_embeddings=config.normalize_embeddings,
            dimension=32,
        )
    )
    return mock, "mock_validation_only", False


def collection_metadata(config: EmbeddingConfig, build_mode: str) -> dict[str, Any]:
    return {
        "index_version": INDEX_VERSION,
        "embedding_model": config.model_name if build_mode == "real_bge_m3" else "deterministic-mock",
        "embedding_normalized": config.normalize_embeddings,
        "processing_version": chunk_processing_version(),
        "build_mode": build_mode,
        "hnsw:space": "cosine",
    }


def chunk_processing_version() -> str:
    if CHUNK_SUMMARY.exists():
        return json.loads(CHUNK_SUMMARY.read_text(encoding="utf-8")).get("processing_version", "unknown")
    return "unknown"


def build_index(
    chunks: list[dict[str, Any]],
    provider: EmbeddingProvider,
    persist_dir: Path,
    collection: str,
    rebuild: bool = False,
    batch_size: int | None = None,
    build_mode: str = "mock_validation_only",
    store_kind: str = "json",
) -> dict[str, Any]:
    metadata = collection_metadata(provider.config, build_mode)
    store = ChromaVectorStore(persist_dir, collection, metadata) if store_kind == "chroma" else JsonVectorStore(persist_dir, collection, metadata)
    if rebuild:
        store.reset_collection()
    batch = batch_size or provider.config.batch_size
    inserted = updated = skipped = failed = embedded = 0
    failures: list[dict[str, Any]] = []
    for start in range(0, len(chunks), batch):
        current = chunks[start : start + batch]
        try:
            ids = [chunk["chunk_id"] for chunk in current]
            metadatas = [metadata_for_chroma(chunk, index_fingerprint(chunk, provider.config)) for chunk in current]
            existing = store.existing_fingerprints(ids)
            pending = [(chunk, chunk_metadata) for chunk, chunk_metadata in zip(current, metadatas) if existing.get(chunk["chunk_id"]) != chunk_metadata["index_fingerprint"]]
            skipped += len(current) - len(pending)
            if not pending:
                continue
            pending_chunks = [chunk for chunk, _metadata in pending]
            pending_metadatas = [chunk_metadata for _chunk, chunk_metadata in pending]
            vectors = provider.embed_documents([chunk["chunk_text"] for chunk in pending_chunks])
            embedded += len(vectors)
            dimension = validate_vectors(vectors, provider.embedding_dimension)
            counts = store.upsert_chunks(
                [chunk["chunk_id"] for chunk in pending_chunks],
                vectors,
                [chunk["chunk_text"] for chunk in pending_chunks],
                pending_metadatas,
            )
            inserted += counts["inserted"]
            updated += counts["updated"]
            skipped += counts["skipped_unchanged"]
        except Exception as exc:
            failed += len(current)
            failures.append({"chunk_ids": [chunk["chunk_id"] for chunk in current], "error_type": type(exc).__name__, "message": str(exc)[:200]})
            dimension = provider.embedding_dimension
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped_unchanged": skipped,
        "embedded": embedded,
        "failed": failed,
        "failures": failures,
        "final_collection_count": store.count(),
        "embedding_dimension": provider.embedding_dimension,
    }


def summarize(chunks: list[dict[str, Any]], build: dict[str, Any], collection: str, persist_dir: Path, config: EmbeddingConfig, build_mode: str) -> dict[str, Any]:
    return {
        "index_version": INDEX_VERSION,
        "collection_name": collection,
        "embedding_model": config.model_name if build_mode == "real_bge_m3" else "deterministic-mock",
        "embedding_dimension": build.get("embedding_dimension"),
        "normalized": config.normalize_embeddings,
        "input_chunk_count": len(chunks),
        "indexed_chunk_count": build.get("final_collection_count", 0),
        "failed_chunk_count": build.get("failed", 0),
        "document_count": len({chunk["document_id"] for chunk in chunks}),
        "source_type_counts": dict(sorted(Counter(chunk.get("text_source_type") for chunk in chunks).items())),
        "regime_counts": dict(sorted(Counter(chunk.get("effective_legal_regime") for chunk in chunks).items())),
        "family_counts": dict(sorted(Counter(chunk.get("effective_offence_family") for chunk in chunks).items())),
        "build_timestamp": datetime.now(UTC).isoformat(),
        "build_mode": build_mode,
        "persist_dir": relative_or_placeholder(persist_dir),
        "inserted": build.get("inserted", 0),
        "updated": build.get("updated", 0),
        "skipped_unchanged": build.get("skipped_unchanged", 0),
        "collection_count": build.get("final_collection_count", 0),
        "embedded": build.get("embedded", 0),
        "store_kind": "chroma" if build_mode == "real_bge_m3" else "json",
        "failures": build.get("failures", []),
        "model_available_locally": bge_m3_available(),
        "embedding_library_versions": installed_versions(["FlagEmbedding", "chromadb", "torch", "transformers", "huggingface-hub"]),
        "embedding_device": config.device,
        "embedding_batch_size": config.batch_size,
        "score_semantics": "Chroma cosine distance is converted to similarity_score = 1 - distance; larger is better." if build_mode == "real_bge_m3" else "JSON validation store uses cosine similarity; larger is better.",
        "semantic_validation": "completed" if build_mode == "real_bge_m3" else "deferred_until_real_bge_m3_available",
    }


def installed_versions(names: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    return versions


def relative_or_placeholder(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return "<external-configured-path>"


def write_docs(summary: dict[str, Any], semantic_rows: list[dict[str, Any]] | None = None) -> None:
    lines = [
        "# Embedding And Vector Index Foundation",
        "",
        "This phase validates dense embedding/index infrastructure over trusted 0.5A chunks only. It does not implement BM25, hybrid retrieval, reranking, RAG generation, Gemini, Ollama, or InLegalBERT.",
        "",
        "## Scope",
        "",
        f"- documents: {summary['document_count']}",
        f"- chunks: {summary['input_chunk_count']}",
        f"- build mode: `{summary['build_mode']}`",
        f"- model: `{summary['embedding_model']}`",
        f"- BGE-M3 locally available: {summary['model_available_locally']}",
        "",
        "## Configuration",
        "",
        "- `EMBEDDING_MODEL=BAAI/bge-m3`",
        "- `EMBEDDING_DEVICE=cpu`",
        "- `EMBEDDING_BATCH_SIZE=16`",
        "- `EMBEDDING_NORMALIZE=true`",
        "- `CHROMA_COLLECTION_NAME=legalai_trusted_judgments_v1`",
        "- `CHROMA_PERSIST_DIR=./chroma_store`",
        "",
        "## Indexing",
        "",
        "Chunks are indexed with deterministic chunk IDs and fingerprints based on chunk ID, chunk text hash, embedding model/config, and index version. Re-running unchanged inputs skips unchanged vectors.",
        "",
        "Chroma metadata nulls are represented reversibly: page/date absence uses sentinel metadata values plus flags such as `has_page_provenance`; source text remains the stored document content.",
        "",
        f"Score semantics: {summary['score_semantics']}",
        "",
        "## CLI",
        "",
        "```bash",
        "python3 backend/scripts/build_vector_index.py --dry-run",
        "python3 backend/scripts/build_vector_index.py --real --rebuild",
        "python3 backend/scripts/build_vector_index.py --stats",
        "```",
        "",
    ]
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")
    qa = ["# Vector Index QA", ""]
    if summary["build_mode"] != "real_bge_m3":
        qa.extend([
            "REAL BGE-M3 INDEX BUILD DEFERRED — MODEL NOT LOCALLY AVAILABLE",
            "",
            "Semantic validation is deferred. Mock embeddings validate IDs, metadata, persistence, fingerprinting, and query plumbing only.",
        ])
    else:
        qa.extend(["Chroma cosine distance is converted to `similarity_score = 1 - distance`; larger is better.", "", "| Query | Top Result | Family | Regime | Page | Similarity Score |", "| --- | --- | --- | --- | --- | ---: |"])
        for row in semantic_rows or []:
            qa.append(f"| {row['query']} | {row['chunk_id']} | {row['family']} | {row['regime']} | {row['page']} | {row['score']} |")
    VECTOR_QA.write_text("\n".join(qa) + "\n", encoding="utf-8")


def run_semantic_qa(provider: EmbeddingProvider, persist_dir: Path, collection: str, build_mode: str) -> list[dict[str, Any]]:
    if build_mode != "real_bge_m3":
        return []
    store = ChromaVectorStore(persist_dir, collection, collection_metadata(provider.config, build_mode))
    rows: list[dict[str, Any]] = []
    for query in SEMANTIC_QUERIES:
        results = store.query_dense(provider.embed_query(query), top_k=5)
        if not results:
            rows.append({"query": query, "chunk_id": "<no-result>", "family": "", "regime": "", "page": "", "score": ""})
            continue
        top = results[0]
        page = f"{top.page_start}-{top.page_end}" if top.page_start is not None else ""
        rows.append(
            {
                "query": query,
                "chunk_id": top.chunk_id,
                "family": top.effective_offence_family or "",
                "regime": top.effective_legal_regime or "",
                "page": page,
                "score": f"{top.score:.6f}",
            }
        )
    return rows


def smoke_embedding(config: EmbeddingConfig) -> dict[str, Any]:
    provider = BgeM3EmbeddingProvider(config)
    texts = ["murder conviction section 302 IPC", "dowry death section 304B IPC", "anticipatory bail under BNSS"]
    vectors = provider.embed_documents(texts)
    return {
        "model": config.model_name,
        "device": config.device,
        "batch_size": config.batch_size,
        "vector_count": len(vectors),
        "dimension": validate_vectors(vectors, provider.embedding_dimension),
        "query_dimension": len(provider.embed_query("criminal breach of trust section 406 IPC")),
        "versions": installed_versions(["FlagEmbedding", "torch", "transformers", "huggingface-hub"]),
    }


def dry_run_summary(chunks: list[dict[str, Any]], collection: str, persist_dir: Path, config: EmbeddingConfig) -> dict[str, Any]:
    return {
        "dry_run": True,
        "collection": collection,
        "persist_dir": relative_or_placeholder(persist_dir),
        "expected_chunks": len(chunks),
        "documents": len({chunk["document_id"] for chunk in chunks}),
        "would_embed": 0,
        "would_mutate_vector_store": False,
        "model_available_locally": bge_m3_available(),
        "configured_model": config.model_name,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    # Same resolution as ingestion and the query path (CHROMA_* env vars or .env).
    configured_persist_dir, configured_collection = resolve_chroma_location(Settings())
    parser.add_argument("--collection", default=configured_collection)
    parser.add_argument("--persist-dir", type=Path, default=configured_persist_dir)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--real", action="store_true", help="Use real local BGE-M3 if available.")
    parser.add_argument("--smoke", action="store_true", help="Load real BGE-M3 and embed a tiny validation set.")
    parser.add_argument("--semantic-qa", action="store_true", help="Run seven semantic sanity queries and write docs/VECTOR_INDEX_QA.md.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    args = build_parser().parse_args(argv)
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    device = os.getenv("EMBEDDING_DEVICE", "cpu")
    normalize = os.getenv("EMBEDDING_NORMALIZE", "true").lower() in {"1", "true", "yes"}
    config = EmbeddingConfig(model_name=model, device=device, batch_size=args.batch_size, normalize_embeddings=normalize)
    if args.smoke:
        print(json.dumps(smoke_embedding(config), indent=2, ensure_ascii=False))
        return 0
    chunks = load_chunks(limit=args.limit, document_id=args.document_id)
    if args.dry_run:
        print(json.dumps(dry_run_summary(chunks, args.collection, args.persist_dir, config), indent=2))
        return 0
    provider, build_mode, available = provider_from_config(args.real and bge_m3_available(), config)
    store_kind = "chroma" if build_mode == "real_bge_m3" else "json"
    build = build_index(chunks, provider, args.persist_dir, args.collection, rebuild=args.rebuild, batch_size=args.batch_size, build_mode=build_mode, store_kind=store_kind)
    summary = summarize(chunks, build, args.collection, args.persist_dir, provider.config, build_mode)
    VECTOR_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    semantic_rows = run_semantic_qa(provider, args.persist_dir, args.collection, build_mode) if args.semantic_qa else None
    write_docs(summary, semantic_rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not available:
        print("REAL BGE-M3 INDEX BUILD DEFERRED — MODEL NOT LOCALLY AVAILABLE")
    return 0 if summary["failed_chunk_count"] == 0 else 1


if __name__ == "__main__":
    load_project_env()
    raise SystemExit(main())
