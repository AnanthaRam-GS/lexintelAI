"""Build the BM25 lexical index for trusted judgment chunks."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_B, DEFAULT_INDEX_NAME, DEFAULT_K1, LEXICAL_INDEX_VERSION, TOKENIZER_VERSION, chunk_universe_fingerprint
from backend.scripts.build_vector_index import CHUNK_DIR, REPO_ROOT, load_chunks, relative_or_placeholder


DEFAULT_PERSIST_DIR = REPO_ROOT / "bm25_store"
LEXICAL_SUMMARY = REPO_ROOT / "data/structured/manifests/trusted_judgment_lexical_index_summary.json"


def dry_run(chunks: list[dict[str, Any]], persist_dir: Path, index_name: str, config: Bm25Config) -> dict[str, Any]:
    ids = [chunk["chunk_id"] for chunk in chunks]
    return {
        "dry_run": True,
        "index_version": LEXICAL_INDEX_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "index_name": index_name,
        "persist_dir": relative_or_placeholder(persist_dir),
        "expected_chunks": len(chunks),
        "documents": len({chunk["document_id"] for chunk in chunks}),
        "duplicate_chunk_ids": len(ids) - len(set(ids)),
        "would_mutate_index": False,
        "k1": config.k1,
        "b": config.b,
        "chunk_universe_fingerprint": chunk_universe_fingerprint(chunks),
    }


def summarize(chunks: list[dict[str, Any]], build: dict[str, Any], index: Bm25LexicalIndex, persist_dir: Path) -> dict[str, Any]:
    ids = [chunk["chunk_id"] for chunk in chunks]
    return {
        "index_version": LEXICAL_INDEX_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "index_name": index.index_name,
        "persist_dir": relative_or_placeholder(persist_dir),
        "chunk_count": len(chunks),
        "document_count": len({chunk["document_id"] for chunk in chunks}),
        "indexed_chunk_count": index.count(),
        "duplicate_chunk_ids": len(ids) - len(set(ids)),
        "empty_tokenized_docs": index.metadata.get("empty_tokenized_docs", 0),
        "chunk_universe_fingerprint": index.metadata.get("chunk_universe_fingerprint"),
        "k1": index.config.k1,
        "b": index.config.b,
        "build_timestamp": datetime.now(UTC).isoformat(),
        "build": build,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persist-dir", type=Path, default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--k1", type=float, default=DEFAULT_K1)
    parser.add_argument("--b", type=float, default=DEFAULT_B)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chunks = load_chunks(CHUNK_DIR, limit=args.limit, document_id=args.document_id)
    config = Bm25Config(k1=args.k1, b=args.b)
    if args.dry_run:
        print(json.dumps(dry_run(chunks, args.persist_dir, args.index_name, config), indent=2, ensure_ascii=False))
        return 0
    index = Bm25LexicalIndex(args.persist_dir, args.index_name, config)
    if args.rebuild:
        index.reset()
    build = {"stats_only": True, "indexed_chunks": index.count()} if args.stats and index.count() else index.build(chunks, rebuild=args.rebuild)
    summary = summarize(chunks, build, index, args.persist_dir)
    LEXICAL_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["indexed_chunk_count"] == len(chunks) and summary["duplicate_chunk_ids"] == 0 and summary["empty_tokenized_docs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
