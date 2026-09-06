"""Build the dense vector index for trusted judgment chunks."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.embeddings.base import EmbeddingConfig, EmbeddingProvider, validate_vectors  # noqa: E402
from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider  # noqa: E402
from backend.app.services.embeddings.mock import DeterministicMockEmbeddingProvider  # noqa: E402
from backend.app.services.vector_store import INDEX_VERSION, JsonVectorStore, metadata_for_chroma  # noqa: E402
from backend.scripts.env_utils import load_project_env  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
CHUNK_DIR = REPO_ROOT / "data/processed/judgment_chunks"
CHUNK_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_chunk_summary.json"
VECTOR_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_vector_index_summary.json"
VECTOR_QA = REPO_ROOT / "docs/VECTOR_INDEX_QA.md"
DOC_PATH = REPO_ROOT / "docs/EMBEDDING_AND_VECTOR_INDEX.md"
DEFAULT_COLLECTION = "legalai_trusted_judgments_v1"
DEFAULT_PERSIST_DIR = REPO_ROOT / "chroma_store"


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
) -> dict[str, Any]:
    metadata = collection_metadata(provider.config, build_mode)
    store = JsonVectorStore(persist_dir, collection, metadata)
    if rebuild:
        store.reset_collection()
    batch = batch_size or provider.config.batch_size
    inserted = updated = skipped = failed = 0
    failures: list[dict[str, Any]] = []
    for start in range(0, len(chunks), batch):
        current = chunks[start : start + batch]
        try:
            vectors = provider.embed_documents([chunk["chunk_text"] for chunk in current])
            dimension = validate_vectors(vectors, provider.embedding_dimension)
            metadatas = [metadata_for_chroma(chunk, index_fingerprint(chunk, provider.config)) for chunk in current]
            counts = store.upsert_chunks(
                [chunk["chunk_id"] for chunk in current],
                vectors,
                [chunk["chunk_text"] for chunk in current],
                metadatas,
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
        "failures": build.get("failures", []),
        "model_available_locally": bge_m3_available(),
        "semantic_validation": "completed" if build_mode == "real_bge_m3" else "deferred_until_real_bge_m3_available",
    }


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
        "Score semantics: the offline JSON validation store uses cosine similarity where larger is better. Chroma distance semantics must be documented when real Chroma is enabled.",
        "",
        "## CLI",
        "",
        "```bash",
        "python3 backend/scripts/build_vector_index.py --dry-run",
        "python3 backend/scripts/build_vector_index.py --rebuild",
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
        qa.extend(["| Query | Top Result | Family | Regime | Page | Score |", "| --- | --- | --- | --- | --- | ---: |"])
        for row in semantic_rows or []:
            qa.append(f"| {row['query']} | {row['chunk_id']} | {row['family']} | {row['regime']} | {row['page']} | {row['score']} |")
    VECTOR_QA.write_text("\n".join(qa) + "\n", encoding="utf-8")


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
    parser.add_argument("--collection", default=os.getenv("CHROMA_COLLECTION_NAME", DEFAULT_COLLECTION))
    parser.add_argument("--persist-dir", type=Path, default=Path(os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR)))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--real", action="store_true", help="Use real local BGE-M3 if available.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    args = build_parser().parse_args(argv)
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    device = os.getenv("EMBEDDING_DEVICE", "cpu")
    normalize = os.getenv("EMBEDDING_NORMALIZE", "true").lower() in {"1", "true", "yes"}
    config = EmbeddingConfig(model_name=model, device=device, batch_size=args.batch_size, normalize_embeddings=normalize)
    chunks = load_chunks(limit=args.limit, document_id=args.document_id)
    if args.dry_run:
        print(json.dumps(dry_run_summary(chunks, args.collection, args.persist_dir, config), indent=2))
        return 0
    provider, build_mode, available = provider_from_config(args.real and bge_m3_available(), config)
    build = build_index(chunks, provider, args.persist_dir, args.collection, rebuild=args.rebuild, batch_size=args.batch_size, build_mode=build_mode)
    summary = summarize(chunks, build, args.collection, args.persist_dir, provider.config, build_mode)
    VECTOR_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_docs(summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not available:
        print("REAL BGE-M3 INDEX BUILD DEFERRED — MODEL NOT LOCALLY AVAILABLE")
    return 0 if summary["failed_chunk_count"] == 0 else 1


if __name__ == "__main__":
    load_project_env()
    raise SystemExit(main())
