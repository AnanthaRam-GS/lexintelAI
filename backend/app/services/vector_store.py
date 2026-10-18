"""Vector-store abstractions for dense chunk retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


INDEX_VERSION = "legalai-chroma-index-v1"
# BGE-M3 dense embedding width; the trusted collection must use it.
EXPECTED_EMBEDDING_DIMENSION = 1024


class VectorStoreUnavailable(RuntimeError):
    """The configured Chroma collection cannot be used; ``code`` is safe to expose."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    document_id: str
    text: str
    score: float
    rank: int
    case_title: str | None
    court: dict[str, Any] | None
    decision_date: str | None
    source_url: str | None
    page_start: int | None
    page_end: int | None
    paragraph_start: int
    paragraph_end: int
    effective_offence_family: str | None
    effective_legal_regime: str | None
    text_source_type: str | None
    retrieval_mode: str = "dense"
    dense_rank: int | None = None
    dense_score: float | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    pre_rerank_rank: int | None = None
    pre_rerank_score: float | None = None


def result_matches_filters(result: RetrievalResult, filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    if filters.get("effective_legal_regime") and result.effective_legal_regime != filters["effective_legal_regime"]:
        return False
    if filters.get("effective_offence_family") and result.effective_offence_family != filters["effective_offence_family"]:
        return False
    court = filters.get("court")
    if court:
        result_court = result.court or {}
        court_value = str(court).casefold()
        if court_value not in str(result_court.get("court_name", "")).casefold() and court_value != str(result_court.get("court_level", "")).casefold():
            return False
    return True


def metadata_matches_filters(metadata: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    if filters.get("effective_legal_regime") and metadata.get("effective_legal_regime") != filters["effective_legal_regime"]:
        return False
    if filters.get("effective_offence_family") and metadata.get("effective_offence_family") != filters["effective_offence_family"]:
        return False
    court = filters.get("court")
    if court:
        try:
            metadata_court = json.loads(metadata.get("court") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata_court = {}
        court_value = str(court).casefold()
        if court_value not in str(metadata_court.get("court_name", "")).casefold() and court_value != str(metadata_court.get("court_level", "")).casefold():
            return False
    return True


def filters_to_chroma_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    clauses: list[dict[str, Any]] = []
    if filters.get("effective_legal_regime"):
        clauses.append({"effective_legal_regime": filters["effective_legal_regime"]})
    if filters.get("effective_offence_family"):
        clauses.append({"effective_offence_family": filters["effective_offence_family"]})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def metadata_for_chroma(chunk: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "chunk_id": chunk["chunk_id"],
        "document_id": chunk["document_id"],
        "provider": chunk["provider"],
        "source_document_id": chunk["source_document_id"],
        "source_url": chunk.get("source_url"),
        "case_title": chunk.get("case_title"),
        "court": json.dumps(chunk.get("court") or {}, ensure_ascii=False),
        "decision_date": chunk.get("decision_date") or "",
        "decision_year": int(chunk["decision_year"]) if chunk.get("decision_year") is not None else -1,
        "effective_offence_family": chunk.get("effective_offence_family"),
        "effective_legal_regime": chunk.get("effective_legal_regime"),
        "chunk_index": int(chunk["chunk_index"]),
        "paragraph_start": int(chunk["paragraph_start"]),
        "paragraph_end": int(chunk["paragraph_end"]),
        "page_start": int(chunk["page_start"]) if chunk.get("page_start") is not None else -1,
        "page_end": int(chunk["page_end"]) if chunk.get("page_end") is not None else -1,
        "has_page_provenance": chunk.get("page_start") is not None and chunk.get("page_end") is not None,
        "text_source_type": chunk.get("text_source_type"),
        "raw_sha256": chunk.get("raw_sha256"),
        "normalizer_version": chunk.get("normalizer_version"),
        "chunker_version": chunk.get("chunker_version"),
        "index_fingerprint": fingerprint,
    }
    return {key: value for key, value in metadata.items() if value is not None}


class JsonVectorStore:
    """Small persistent store with Chroma-like semantics for offline validation."""

    def __init__(self, persist_dir: Path, collection_name: str, collection_metadata: dict[str, Any]) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.collection_metadata = collection_metadata
        self.path = persist_dir / f"{collection_name}.json"
        self.records: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            existing = payload.get("metadata", {})
            if existing.get("index_version") != collection_metadata.get("index_version"):
                raise ValueError("index version mismatch; rebuild or use a new collection")
            self.records = {record["id"]: record for record in payload.get("records", [])}

    def persist(self) -> None:
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        payload = {"metadata": self.collection_metadata, "records": list(self.records.values())}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def reset_collection(self) -> None:
        self.records = {}
        if self.path.exists():
            self.path.unlink()

    def upsert_chunks(
        self,
        ids: list[str],
        vectors: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> dict[str, int]:
        inserted = 0
        updated = 0
        skipped = 0
        for item_id, vector, document, metadata in zip(ids, vectors, documents, metadatas):
            existing = self.records.get(item_id)
            if existing and existing.get("metadata", {}).get("index_fingerprint") == metadata.get("index_fingerprint"):
                skipped += 1
                continue
            if existing:
                updated += 1
            else:
                inserted += 1
            self.records[item_id] = {"id": item_id, "embedding": vector, "document": document, "metadata": metadata}
        self.persist()
        return {"inserted": inserted, "updated": updated, "skipped_unchanged": skipped}

    def existing_fingerprints(self, ids: list[str]) -> dict[str, str]:
        return {
            item_id: record["metadata"]["index_fingerprint"]
            for item_id, record in self.records.items()
            if item_id in ids and record.get("metadata", {}).get("index_fingerprint")
        }

    def count(self) -> int:
        return len(self.records)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.records.get(chunk_id)

    def delete_document(self, document_id: str) -> int:
        ids = [item_id for item_id, record in self.records.items() if record["metadata"].get("document_id") == document_id]
        for item_id in ids:
            del self.records[item_id]
        self.persist()
        return len(ids)

    def query_dense(self, vector: list[float], top_k: int = 5, filters: dict[str, Any] | None = None) -> list[RetrievalResult]:
        scored = sorted(
            (
                (cosine_similarity(vector, record["embedding"]), record)
                for record in self.records.values()
                if metadata_matches_filters(record["metadata"], filters)
            ),
            key=lambda item: item[0],
            reverse=True,
        )[:top_k]
        results: list[RetrievalResult] = []
        for rank, (score, record) in enumerate(scored, start=1):
            metadata = record["metadata"]
            court = json.loads(metadata.get("court") or "{}")
            results.append(
                RetrievalResult(
                    chunk_id=record["id"],
                    document_id=metadata["document_id"],
                    text=record["document"],
                    score=score,
                    rank=rank,
                    case_title=metadata.get("case_title"),
                    court=court,
                    decision_date=metadata.get("decision_date") or None,
                    source_url=metadata.get("source_url"),
                    page_start=metadata.get("page_start") if metadata.get("has_page_provenance") else None,
                    page_end=metadata.get("page_end") if metadata.get("has_page_provenance") else None,
                    paragraph_start=metadata["paragraph_start"],
                    paragraph_end=metadata["paragraph_end"],
                    effective_offence_family=metadata.get("effective_offence_family"),
                    effective_legal_regime=metadata.get("effective_legal_regime"),
                    text_source_type=metadata.get("text_source_type"),
                )
            )
        return results

    def collection_metadata_value(self) -> dict[str, Any]:
        return self.collection_metadata


class ChromaVectorStore:
    """Thin optional Chroma adapter; requires chromadb to be installed locally."""

    def __init__(
        self,
        persist_dir: Path,
        collection_name: str,
        collection_metadata: dict[str, Any],
        *,
        create_if_missing: bool = True,
        expected_dimension: int | None = None,
    ) -> None:
        """Open (and, for ingestion and index builds, create) a collection.

        Read paths pass ``create_if_missing=False``: a missing store or
        collection then raises VectorStoreUnavailable instead of silently
        creating an empty one, and ``expected_dimension`` is enforced.
        """
        try:
            import chromadb
            from chromadb.errors import NotFoundError
        except ImportError as exc:
            raise RuntimeError("chromadb is required for real Chroma persistence") from exc
        self.collection_name = collection_name
        if create_if_missing:
            self._client = chromadb.PersistentClient(path=str(persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata=collection_metadata,
            )
        else:
            # PersistentClient creates the directory and database when absent,
            # so check for the store before opening it.
            if not (Path(persist_dir) / "chroma.sqlite3").is_file():
                raise VectorStoreUnavailable("VECTOR_STORE_MISSING", "The vector store does not exist.")
            self._client = chromadb.PersistentClient(path=str(persist_dir))
            try:
                self._collection = self._client.get_collection(name=collection_name)
            except (NotFoundError, ValueError) as exc:
                raise VectorStoreUnavailable(
                    "VECTOR_COLLECTION_MISSING", f"The vector collection '{collection_name}' does not exist."
                ) from exc
        if expected_dimension is not None:
            dimension = self.dimension()
            if dimension != expected_dimension:
                raise VectorStoreUnavailable(
                    "VECTOR_DIMENSION_MISMATCH",
                    f"The vector collection '{collection_name}' has embedding dimension {dimension}, "
                    f"expected {expected_dimension}.",
                )
        self.collection_metadata = collection_metadata

    def dimension(self) -> int | None:
        """Embedding width recorded by Chroma; None until the first vector is written."""
        return getattr(self._collection._model, "dimension", None)

    def upsert_chunks(
        self,
        ids: list[str],
        vectors: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> dict[str, int]:
        existing = set(self._collection.get(ids=ids, include=[])["ids"])
        self._collection.upsert(ids=ids, embeddings=vectors, documents=documents, metadatas=metadatas)
        return {
            "inserted": len([item_id for item_id in ids if item_id not in existing]),
            "updated": len([item_id for item_id in ids if item_id in existing]),
            "skipped_unchanged": 0,
        }

    def existing_fingerprints(self, ids: list[str]) -> dict[str, str]:
        existing = self._collection.get(ids=ids, include=["metadatas"])
        fingerprints: dict[str, str] = {}
        for item_id, metadata in zip(existing.get("ids", []), existing.get("metadatas", []) or []):
            fingerprint = (metadata or {}).get("index_fingerprint")
            if isinstance(fingerprint, str):
                fingerprints[item_id] = fingerprint
        return fingerprints

    def count(self) -> int:
        return int(self._collection.count())

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        existing = self._collection.get(ids=[chunk_id], include=["embeddings", "documents", "metadatas"])
        if not existing.get("ids"):
            return None
        embeddings = existing.get("embeddings")
        return {
            "id": existing["ids"][0],
            "embedding": embeddings[0] if embeddings is not None and len(embeddings) else None,
            "document": (existing.get("documents") or [""])[0],
            "metadata": (existing.get("metadatas") or [{}])[0],
        }

    def delete_document(self, document_id: str) -> int:
        existing = self._collection.get(where={"document_id": document_id}, include=[])
        ids = existing.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def query_dense(self, vector: list[float], top_k: int = 5, filters: dict[str, Any] | None = None) -> list[RetrievalResult]:
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        where = filters_to_chroma_where(filters)
        if where:
            query_kwargs["where"] = where
        queried = self._collection.query(**query_kwargs)
        ids = queried.get("ids", [[]])[0]
        documents = queried.get("documents", [[]])[0]
        metadatas = queried.get("metadatas", [[]])[0]
        distances = queried.get("distances", [[]])[0]
        results: list[RetrievalResult] = []
        for rank, (item_id, document, metadata, distance) in enumerate(zip(ids, documents, metadatas, distances), start=1):
            metadata = metadata or {}
            court = json.loads(metadata.get("court") or "{}")
            page_start = metadata.get("page_start") if metadata.get("has_page_provenance") else None
            page_end = metadata.get("page_end") if metadata.get("has_page_provenance") else None
            results.append(
                RetrievalResult(
                    chunk_id=item_id,
                    document_id=metadata["document_id"],
                    text=document,
                    score=1.0 - float(distance),
                    rank=rank,
                    case_title=metadata.get("case_title"),
                    court=court,
                    decision_date=metadata.get("decision_date") or None,
                    source_url=metadata.get("source_url"),
                    page_start=page_start,
                    page_end=page_end,
                    paragraph_start=int(metadata["paragraph_start"]),
                    paragraph_end=int(metadata["paragraph_end"]),
                    effective_offence_family=metadata.get("effective_offence_family"),
                    effective_legal_regime=metadata.get("effective_legal_regime"),
                    text_source_type=metadata.get("text_source_type"),
                )
            )
        return results

    def reset_collection(self) -> None:
        ids = self._collection.get(include=[])["ids"]
        if ids:
            self._collection.delete(ids=ids)

    def collection_metadata_value(self) -> dict[str, Any]:
        return self.collection_metadata
