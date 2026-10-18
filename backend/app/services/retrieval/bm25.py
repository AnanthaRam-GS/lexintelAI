"""Deterministic local BM25 retrieval over trusted judgment chunks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any

from backend.app.services.vector_store import RetrievalResult, metadata_matches_filters, metadata_for_chroma


LEXICAL_INDEX_VERSION = "legalai-bm25-index-v1"
TOKENIZER_VERSION = "legalai-legal-tokenizer-v1"
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75
DEFAULT_INDEX_NAME = "legalai_trusted_judgments_bm25_v1"

TOKEN_PATTERN = re.compile(r"[a-z]+(?:\.[a-z]+)*|\d+[a-z]?(?:-\d+[a-z]?|-[a-z])?")


@dataclass(frozen=True)
class Bm25Config:
    k1: float = DEFAULT_K1
    b: float = DEFAULT_B


def tokenize_legal_text(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"\b(i)\s*\.\s*(p)\s*\.\s*(c)\b", "ipc", normalized)
    normalized = re.sub(r"\b(c)\s*r\s*\.\s*(p)\s*\.\s*(c)\b", "crpc", normalized)
    tokens: list[str] = []
    for token in TOKEN_PATTERN.findall(normalized):
        compact = token.replace(".", "")
        tokens.append(compact)
        if re.fullmatch(r"\d+-[a-z]", compact):
            tokens.append(compact.replace("-", ""))
        elif re.fullmatch(r"\d+[a-z]", compact):
            tokens.append(f"{compact[:-1]}-{compact[-1]}")
    return tokens


def chunk_universe_fingerprint(chunks: list[dict[str, Any]]) -> str:
    payload = [
        {
            "chunk_id": chunk["chunk_id"],
            "document_id": chunk["document_id"],
            "text_hash": hashlib.sha256(str(chunk.get("chunk_text") or "").encode("utf-8")).hexdigest(),
            "normalizer_version": chunk.get("normalizer_version"),
            "chunker_version": chunk.get("chunker_version"),
        }
        for chunk in sorted(chunks, key=lambda row: row["chunk_id"])
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class Bm25LexicalIndex:
    def __init__(self, persist_dir: Path, index_name: str = DEFAULT_INDEX_NAME, config: Bm25Config | None = None) -> None:
        self.persist_dir = persist_dir
        self.index_name = index_name
        self.config = config or Bm25Config()
        self.path = persist_dir / f"{index_name}.json"
        self.metadata: dict[str, Any] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.doc_freqs: dict[str, int] = {}
        self.avg_doc_length = 0.0
        if self.path.exists():
            self.load()

    def build(self, chunks: list[dict[str, Any]], rebuild: bool = False) -> dict[str, Any]:
        if self.path.exists() and not rebuild:
            self.load()
            expected = chunk_universe_fingerprint(chunks)
            if self.metadata.get("chunk_universe_fingerprint") != expected:
                raise ValueError("chunk universe mismatch; rebuild lexical index")
            return {"inserted": 0, "updated": 0, "skipped_unchanged": len(chunks), "indexed_chunks": self.count()}
        duplicate_ids = len(chunks) - len({chunk["chunk_id"] for chunk in chunks})
        if duplicate_ids:
            raise ValueError(f"duplicate chunk IDs: {duplicate_ids}")
        self.records = {}
        doc_freq_counter: Counter[str] = Counter()
        empty_tokenized_docs = 0
        for chunk in chunks:
            tokens = tokenize_legal_text(chunk["chunk_text"])
            if not tokens:
                empty_tokenized_docs += 1
            frequencies = dict(Counter(tokens))
            doc_freq_counter.update(frequencies.keys())
            self.records[chunk["chunk_id"]] = {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "text": chunk["chunk_text"],
                "metadata": metadata_for_chroma(chunk, ""),
                "term_freqs": frequencies,
                "length": len(tokens),
            }
        self.doc_freqs = dict(doc_freq_counter)
        self.avg_doc_length = sum(record["length"] for record in self.records.values()) / max(len(self.records), 1)
        self.metadata = self.index_metadata(chunks, empty_tokenized_docs)
        self.persist()
        return {
            "inserted": len(chunks),
            "updated": 0,
            "skipped_unchanged": 0,
            "indexed_chunks": self.count(),
            "empty_tokenized_docs": empty_tokenized_docs,
            "duplicate_chunk_ids": duplicate_ids,
        }

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        """Insert or replace trusted chunks while preserving frozen BM25 semantics."""
        if self.path.exists():
            self.load()
        inserted = 0
        updated = 0
        skipped = 0
        empty_tokenized_docs = 0
        seen_ids: set[str] = set()
        for chunk in chunks:
            record = self.record_for_chunk(chunk)
            chunk_id = record["chunk_id"]
            if chunk_id in seen_ids:
                raise ValueError(f"duplicate chunk ID in update batch: {chunk_id}")
            seen_ids.add(chunk_id)
            existing = self.records.get(chunk_id)
            if existing == record:
                skipped += 1
            elif existing:
                self.records[chunk_id] = record
                updated += 1
            else:
                self.records[chunk_id] = record
                inserted += 1
            if record["length"] == 0:
                empty_tokenized_docs += 1
        self.recompute_statistics()
        self.metadata = self.index_metadata_from_records(empty_tokenized_docs)
        self.persist()
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_unchanged": skipped,
            "indexed_chunks": self.count(),
            "empty_tokenized_docs": empty_tokenized_docs,
        }

    def load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        metadata = payload["metadata"]
        if metadata.get("index_version") != LEXICAL_INDEX_VERSION:
            raise ValueError("BM25 index version mismatch; rebuild lexical index")
        self.metadata = metadata
        self.records = {record["chunk_id"]: record for record in payload.get("records", [])}
        self.doc_freqs = payload.get("doc_freqs", {})
        self.avg_doc_length = float(payload.get("avg_doc_length", 0.0))

    def persist(self) -> None:
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": self.metadata,
            "doc_freqs": self.doc_freqs,
            "avg_doc_length": self.avg_doc_length,
            "records": list(self.records.values()),
        }
        serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.persist_dir, delete=False) as handle:
            temp_name = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            json.loads(Path(temp_name).read_text(encoding="utf-8"))
            os.replace(temp_name, self.path)
        finally:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()

    def reset(self) -> None:
        self.records = {}
        self.doc_freqs = {}
        self.avg_doc_length = 0.0
        self.metadata = {}
        if self.path.exists():
            self.path.unlink()

    def count(self) -> int:
        return len(self.records)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.records.get(chunk_id)

    def delete_document(self, document_id: str) -> int:
        ids = [chunk_id for chunk_id, record in self.records.items() if record["document_id"] == document_id]
        for chunk_id in ids:
            del self.records[chunk_id]
        if ids:
            self.persist()
        return len(ids)

    def remove_document(self, document_id: str) -> int:
        """Delete a document's records, then rebuild statistics and index metadata.

        Unlike delete_document, the persisted metadata (counts, fingerprint)
        stays consistent with the remaining records. Used to compensate a
        failed ingestion.
        """
        if self.path.exists():
            self.load()
        ids = [chunk_id for chunk_id, record in self.records.items() if record["document_id"] == document_id]
        if not ids:
            return 0
        for chunk_id in ids:
            del self.records[chunk_id]
        self.recompute_statistics()
        empty = sum(1 for record in self.records.values() if record["length"] == 0)
        self.metadata = self.index_metadata_from_records(empty_tokenized_docs=empty)
        self.persist()
        return len(ids)

    def index_metadata(self, chunks: list[dict[str, Any]], empty_tokenized_docs: int = 0) -> dict[str, Any]:
        processing_versions = sorted({str(chunk.get("chunker_version", "unknown")) for chunk in chunks})
        return {
            "index_version": LEXICAL_INDEX_VERSION,
            "tokenizer_version": TOKENIZER_VERSION,
            "chunk_universe_fingerprint": chunk_universe_fingerprint(chunks),
            "chunk_count": len(chunks),
            "document_count": len({chunk["document_id"] for chunk in chunks}),
            "k1": self.config.k1,
            "b": self.config.b,
            "chunk_processing_versions": processing_versions,
            "empty_tokenized_docs": empty_tokenized_docs,
        }

    def record_for_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        chunk_id = str(chunk["chunk_id"])
        document_id = str(chunk["document_id"])
        text = str(chunk.get("chunk_text") or chunk.get("text") or "")
        normalized = {**chunk, "chunk_id": chunk_id, "document_id": document_id, "chunk_text": text}
        tokens = tokenize_legal_text(text)
        return {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "text": text,
            "metadata": metadata_for_chroma(normalized, ""),
            "term_freqs": dict(Counter(tokens)),
            "length": len(tokens),
        }

    def recompute_statistics(self) -> None:
        doc_freq_counter: Counter[str] = Counter()
        for record in self.records.values():
            doc_freq_counter.update(record["term_freqs"].keys())
        self.doc_freqs = dict(doc_freq_counter)
        self.avg_doc_length = sum(record["length"] for record in self.records.values()) / max(len(self.records), 1)

    def index_metadata_from_records(self, empty_tokenized_docs: int = 0) -> dict[str, Any]:
        chunks = [
            {
                "chunk_id": record["chunk_id"],
                "document_id": record["document_id"],
                "chunk_text": record["text"],
                "normalizer_version": record["metadata"].get("normalizer_version"),
                "chunker_version": record["metadata"].get("chunker_version"),
            }
            for record in self.records.values()
        ]
        return self.index_metadata(chunks, empty_tokenized_docs=empty_tokenized_docs)

    def query(self, query: str, top_k: int = 5, filters: dict[str, Any] | None = None) -> list[RetrievalResult]:
        query_terms = tokenize_legal_text(query)
        if not query_terms:
            return []
        query_counts = Counter(query_terms)
        scored: list[tuple[float, dict[str, Any]]] = []
        n_docs = max(self.count(), 1)
        for record in self.records.values():
            if not metadata_matches_filters(record["metadata"], filters):
                continue
            score = 0.0
            for term, query_weight in query_counts.items():
                term_freq = record["term_freqs"].get(term, 0)
                if not term_freq:
                    continue
                doc_freq = self.doc_freqs.get(term, 0)
                idf = math.log(1 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
                denominator = term_freq + self.config.k1 * (1 - self.config.b + self.config.b * record["length"] / max(self.avg_doc_length, 1))
                score += query_weight * idf * ((term_freq * (self.config.k1 + 1)) / denominator)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [self._to_result(record, score, rank) for rank, (score, record) in enumerate(scored[:top_k], start=1)]

    def _to_result(self, record: dict[str, Any], score: float, rank: int) -> RetrievalResult:
        metadata = record["metadata"]
        court = json.loads(metadata.get("court") or "{}")
        return RetrievalResult(
            chunk_id=record["chunk_id"],
            document_id=record["document_id"],
            text=record["text"],
            score=score,
            rank=rank,
            case_title=metadata.get("case_title"),
            court=court,
            decision_date=metadata.get("decision_date") or None,
            source_url=metadata.get("source_url"),
            page_start=metadata.get("page_start") if metadata.get("has_page_provenance") else None,
            page_end=metadata.get("page_end") if metadata.get("has_page_provenance") else None,
            paragraph_start=int(metadata["paragraph_start"]),
            paragraph_end=int(metadata["paragraph_end"]),
            effective_offence_family=metadata.get("effective_offence_family"),
            effective_legal_regime=metadata.get("effective_legal_regime"),
            text_source_type=metadata.get("text_source_type"),
            retrieval_mode="lexical",
            lexical_rank=rank,
            lexical_score=score,
        )
