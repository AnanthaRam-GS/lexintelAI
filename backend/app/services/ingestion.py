"""Corpus ingestion service and job management for LegalAI.

Job states: QUEUED -> EXTRACTING -> CHUNKING -> EMBEDDING -> INDEXING ->
COMPLETED / FAILED.

Consistency (BE-001). PostgreSQL is canonical; Chroma and BM25 are derived.
An ingestion ends in exactly one of two states:

- COMPLETED: the document is in PostgreSQL, Chroma and BM25;
- FAILED: nothing for the document is left in any store, or, if cleanup
  itself failed, ``needs_reconciliation`` is set on the job.

Ordering: parse, chunk, analyse and embed write nothing. Analysis derives
the cited sections with the document_sections extractor and adds the
index_metadata_v1 fields (``services/index_metadata.py``) and the derived
``effective_legal_regime`` to every chunk. The write phase then upserts
Chroma, then BM25, and commits PostgreSQL **last**, in one transaction that
inserts the document and its chunks, runs the analytics producer for it
(``produce_analytics_data.produce_document``: document_sections, outcomes,
court level) and flips the job to COMPLETED. A failure at any write step rolls back the PostgreSQL transaction
and removes the document's entries from BM25 and Chroma by its
``source_document_key`` (compensating cleanup). The write phase holds a
process-wide lock, so concurrent ingestions and the stale-job reaper cannot
interleave with it. Multi-process deployments need a shared lock.

Duplicates (DATA-003). A document is identified by the SHA-256 of the
uploaded file. The upload endpoint rejects a known checksum with 409 before
any write, and the write phase re-checks under the lock. The unique
constraint on ``documents.checksum`` is the final guard.

Errors (SEC-007). Jobs store a sanitized ``error_message`` and an internal
``error_code``. Raw exception text goes to the server log only, with no
document text and no SQL parameters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
import threading
from typing import Any, Callable
import uuid

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, resolve_chroma_location
from backend.app.db.models import Chunk, Document, IngestionJob
from backend.app.db.session import SessionLocal, check_db_connection
from backend.scripts.produce_analytics_data import desired_sections, new_stats, produce_document
from backend.app.models.ingest import (
    CorpusStatsResponse,
    CorpusTypeCount,
    IngestionStatus,
    IngestionStatusResponse,
    ReconciliationJob,
)

logger = logging.getLogger("legalai.ingestion")

_BM25_INDEX_LOCK = threading.Lock()
# Serializes the index-write + PostgreSQL-commit phase and the reaper's cleanup.
_INGEST_WRITE_LOCK = threading.Lock()

ADMIN_KEY_PREFIX = "admin:"
ADMIN_PROVIDER = "admin_upload"
SECTION_HEADING_MAX = 255
RECONCILIATION_JOBS_SHOWN = 20
NON_TERMINAL_STATUSES = (
    IngestionStatus.QUEUED.value,
    IngestionStatus.EXTRACTING.value,
    IngestionStatus.CHUNKING.value,
    IngestionStatus.EMBEDDING.value,
    IngestionStatus.INDEXING.value,
)

SAFE_MESSAGES = {
    "PARSE_FAILED": "The PDF could not be read.",
    "PDF_NO_TEXT": "The PDF has no extractable text. Scanned PDFs are not supported.",
    "CHUNKING_FAILED": "The document text could not be split into chunks.",
    "EMBEDDING_FAILED": "Embeddings could not be generated for this document.",
    "DUPLICATE_DOCUMENT": "This document has already been ingested.",
    "VECTOR_INDEX_FAILED": "The vector index could not be updated.",
    "LEXICAL_INDEX_FAILED": "The keyword index could not be updated.",
    "DATABASE_WRITE_FAILED": "The document could not be saved to the database.",
    "ANALYTICS_FAILED": "Cited sections and outcomes could not be derived for this document.",
    "STALE_JOB": "Ingestion did not finish within the time limit and was stopped.",
    "INGESTION_FAILED": "Ingestion failed unexpectedly.",
}
RECONCILIATION_SUFFIX = " Cleanup did not complete; the stores need reconciliation."
STAGE_ERROR_CODES = {
    "parse": "PARSE_FAILED",
    "chunk": "CHUNKING_FAILED",
    "embed": "EMBEDDING_FAILED",
    "vector": "VECTOR_INDEX_FAILED",
    "bm25": "LEXICAL_INDEX_FAILED",
    "database": "DATABASE_WRITE_FAILED",
    "analytics": "ANALYTICS_FAILED",
}


class IngestionError(Exception):
    """A failure with a known, user-safe error code."""

    def __init__(self, code: str) -> None:
        super().__init__(SAFE_MESSAGES[code])
        self.code = code


def admin_document_key(checksum: str) -> str:
    """source_document_key for an admin upload; chunk IDs are ``<key>:chunk:<nnnn>``."""
    return f"{ADMIN_KEY_PREFIX}{checksum}"


def find_document_by_checksum(db: Session, checksum: str) -> Document | None:
    return (
        db.query(Document)
        .filter(or_(Document.checksum == checksum, Document.source_document_key == admin_document_key(checksum)))
        .first()
    )


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


def create_ingestion_job(db: Session, job_id: str | None = None) -> IngestionJob:
    """Create a new ingestion job record in QUEUED status."""
    job = IngestionJob(
        id=job_id or str(uuid.uuid4()),
        status=IngestionStatus.QUEUED.value,
        progress=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_ingestion_job(db: Session, job_id: str) -> IngestionJob | None:
    """Retrieve an ingestion job by ID."""
    return db.query(IngestionJob).filter(IngestionJob.id == job_id).first()


def get_job_chunk_count(db: Session, document_id: int | None) -> int:
    """Return count of chunks stored for a document."""
    if not document_id:
        return 0
    return db.query(func.count(Chunk.id)).filter(Chunk.document_id == document_id).scalar() or 0


# --------------------------------------------------------------------------
# Store status (BE-002)
# --------------------------------------------------------------------------


def get_vector_store_status(settings: Settings | None = None, expected_count: int | None = None) -> dict[str, Any]:
    """Health of the configured Chroma collection, opened without creating anything."""
    from backend.app.services.vector_store import (
        EXPECTED_EMBEDDING_DIMENSION,
        INDEX_VERSION,
        ChromaVectorStore,
        VectorStoreUnavailable,
    )

    persist_dir, collection_name = resolve_chroma_location(settings or Settings())
    result: dict[str, Any] = {"status": "down", "detail": None, "collection": collection_name, "count": None}
    try:
        store = ChromaVectorStore(
            persist_dir,
            collection_name,
            {"index_version": INDEX_VERSION},
            create_if_missing=False,
            expected_dimension=EXPECTED_EMBEDDING_DIMENSION,
        )
        result["count"] = store.count()
    except VectorStoreUnavailable as exc:
        result["detail"] = str(exc)
        return result
    except Exception as exc:
        logger.error("vector store status check failed: %s", _log_detail(exc))
        result["detail"] = f"The vector store could not be opened ({type(exc).__name__})."
        return result
    if expected_count is not None and result["count"] != expected_count:
        result["status"] = "degraded"
        result["detail"] = f"{result['count']} vectors but {expected_count} PostgreSQL chunks."
    else:
        result["status"] = "healthy"
    return result


def get_bm25_status(expected_count: int | None = None) -> dict[str, Any]:
    """Health of the BM25 lexical index, read without modifying it."""
    from backend.app.services.retrieval.bm25 import DEFAULT_INDEX_NAME, Bm25LexicalIndex
    from backend.scripts import build_lexical_index

    result: dict[str, Any] = {"status": "down", "detail": None, "count": None}
    path = Path(build_lexical_index.DEFAULT_PERSIST_DIR) / f"{DEFAULT_INDEX_NAME}.json"
    if not path.is_file():
        result["detail"] = "The keyword index does not exist."
        return result
    try:
        index = Bm25LexicalIndex(path.parent, DEFAULT_INDEX_NAME)
    except Exception as exc:
        logger.error("bm25 status check failed: %s", _log_detail(exc))
        result["detail"] = f"The keyword index could not be read ({type(exc).__name__})."
        return result
    result["count"] = index.count()
    if index.metadata.get("chunk_count") != index.count():
        result["status"] = "degraded"
        result["detail"] = "Keyword index metadata does not match its records."
    elif expected_count is not None and index.count() != expected_count:
        result["status"] = "degraded"
        result["detail"] = f"{index.count()} keyword records but {expected_count} PostgreSQL chunks."
    else:
        result["status"] = "healthy"
    return result


def get_corpus_stats(db: Session, settings: Settings | None = None) -> CorpusStatsResponse:
    """Return document counts and the real health of PostgreSQL, Chroma and BM25."""
    total_docs = db.query(func.count(Document.id)).scalar() or 0
    last_updated = db.query(func.max(Document.ingested_at)).scalar()
    type_counts_raw = db.query(Document.doc_type, func.count(Document.id)).group_by(Document.doc_type).all()
    by_type = [CorpusTypeCount(doc_type=row[0], count=row[1]) for row in type_counts_raw]
    pg_chunks = db.query(func.count(Chunk.id)).scalar() or 0

    is_db_ok, _ = check_db_connection()
    chroma = get_vector_store_status(settings, expected_count=pg_chunks)
    bm25 = get_bm25_status(expected_count=pg_chunks)
    flagged = db.query(IngestionJob).filter(IngestionJob.needs_reconciliation.is_(True))
    reconciliation_jobs = [
        ReconciliationJob(job_id=job.id, error_code=job.error_code, error_message=job.error_message, completed_at=job.completed_at)
        for job in flagged.order_by(IngestionJob.completed_at.desc().nullslast(), IngestionJob.id).limit(RECONCILIATION_JOBS_SHOWN)
    ]
    return CorpusStatsResponse(
        total_documents=total_docs,
        last_updated=last_updated,
        by_type=by_type,
        postgres_status="healthy" if is_db_ok else "down",
        chroma_status=chroma["status"],
        chroma_detail=chroma["detail"],
        chroma_collection=chroma["collection"],
        chroma_record_count=chroma["count"],
        bm25_status=bm25["status"],
        bm25_detail=bm25["detail"],
        bm25_record_count=bm25["count"],
        postgres_chunk_count=pg_chunks,
        reconciliation_job_count=flagged.count(),
        reconciliation_jobs=reconciliation_jobs,
    )


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------


def process_ingestion_job(
    job_id: str,
    file_path: str,
    doc_type: str,
    court_level: str | None = None,
    year: int | None = None,
    source_url: str | None = None,
    checksum: str | None = None,
    case_name: str | None = None,
    parser_func: Callable[[str], dict[str, Any]] | None = None,
    chunker_func: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    embedding_provider: Any = None,
    vector_store: Any = None,
    bm25_update_func: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    bm25_remove_func: Callable[[str], int] | None = None,
    retrieval_cache_invalidator: Callable[[], None] | None = None,
) -> None:
    """Run one ingestion job to COMPLETED or FAILED; see the module docstring."""
    db = SessionLocal()
    stage = "start"
    cleanup_failures: list[str] = []
    try:
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            return
        _advance(db, job, IngestionStatus.EXTRACTING, 20, started=True)

        stage = "parse"
        extracted = (parser_func or _default_parser())(file_path)
        checksum = checksum or _content_checksum(extracted, file_path)
        key = admin_document_key(checksum)
        case_title = case_name or Path(file_path).stem
        _prepare_for_chunking(extracted, key, checksum, case_title, court_level, year, source_url)

        _advance(db, job, IngestionStatus.CHUNKING, 40)
        stage = "chunk"
        raw_chunks = (chunker_func or _default_chunker())(extracted)
        if not isinstance(raw_chunks, list) or not raw_chunks:
            raise IngestionError("CHUNKING_FAILED")
        text_source_type = (extracted.get("metadata") or {}).get("text_source_type") or "pdf_native"
        chunks = [
            corpus_format_chunk(raw, position, key, checksum, case_title, court_level, year, source_url, text_source_type)
            for position, raw in enumerate(raw_chunks)
        ]
        if find_document_by_checksum(db, checksum) is not None:
            raise IngestionError("DUPLICATE_DOCUMENT")
        stage = "analytics"
        add_index_metadata(chunks, doc_type)

        _advance(db, job, IngestionStatus.EMBEDDING, 60)
        stage = "embed"
        provider = embedding_provider or _default_embedder()
        vectors = provider.embed_documents([chunk["chunk_text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise IngestionError("EMBEDDING_FAILED")

        _advance(db, job, IngestionStatus.INDEXING, 80)
        with _INGEST_WRITE_LOCK:
            writes = {"vector": False, "bm25": False}
            store = vector_store
            try:
                db.refresh(job)
                if job.status == IngestionStatus.FAILED.value:  # reaped while embedding
                    raise IngestionError("STALE_JOB")
                if find_document_by_checksum(db, checksum) is not None:
                    raise IngestionError("DUPLICATE_DOCUMENT")

                stage = "vector"
                store = store or trusted_vector_store(Settings())
                writes["vector"] = True
                store.upsert_chunks(
                    ids=[chunk["chunk_id"] for chunk in chunks],
                    vectors=vectors,
                    documents=[chunk["chunk_text"] for chunk in chunks],
                    metadatas=chroma_metadatas(chunks, provider),
                )

                stage = "bm25"
                writes["bm25"] = True
                with _BM25_INDEX_LOCK:
                    bm25_result = (bm25_update_func or update_trusted_bm25_index)(chunks)
                if not bm25_result or bm25_result.get("indexed_chunks", 0) < len(chunks):
                    raise IngestionError("LEXICAL_INDEX_FAILED")

                stage = "database"
                document = Document(
                    doc_type=doc_type,
                    case_name=case_title,
                    court_level=court_level,
                    year=year,
                    source_url=source_url,
                    file_path=file_path,
                    checksum=checksum,
                    source_document_key=key,
                )
                document.chunks = [pg_chunk(chunk) for chunk in chunks]
                db.add(document)
                db.flush()
                stage = "analytics"
                produce_document(db, document, analytics_chunks(chunks), new_stats())
                stage = "database"
                job.document = document
                job.status = IngestionStatus.COMPLETED.value
                job.progress = 100
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = None
                job.error_code = None
                db.commit()
            except Exception as exc:
                db.rollback()
                if isinstance(exc, IntegrityError) and _committed_document_exists(db, key, checksum):
                    exc = IngestionError("DUPLICATE_DOCUMENT")  # lost a race with a concurrent upload
                if any(writes.values()):
                    cleanup_failures = compensate_document(
                        db,
                        key,
                        vector_store=store,
                        vector_written=writes["vector"],
                        bm25_written=writes["bm25"],
                        bm25_remove_func=bm25_remove_func,
                    )
                raise exc
        _invalidate(retrieval_cache_invalidator)
    except Exception as exc:
        code = exc.code if isinstance(exc, IngestionError) else _code_for(stage, exc)
        logger.error(
            "ingestion job=%s failed code=%s stage=%s cleanup_failures=%s error=%s",
            job_id, code, stage, cleanup_failures or "none", _log_detail(exc),
        )
        _record_failure(db, job_id, code, cleanup_failures)
    finally:
        db.close()


def compensate_document(
    db: Session,
    document_key: str,
    *,
    vector_store: Any,
    vector_written: bool,
    bm25_written: bool,
    bm25_remove_func: Callable[[str], int] | None = None,
) -> list[str]:
    """Remove a failed document's index entries; return the stores that could not be cleaned.

    Index entries are left alone when PostgreSQL already holds a committed
    document with this key: they then belong to that document (for example a
    concurrent upload of the same file that won the race).
    """
    try:
        db.rollback()
        if _committed_document_exists(db, document_key, None):
            return []
    except Exception as exc:
        logger.error("compensation could not check postgres for %s: %s", document_key, _log_detail(exc))
        return ["postgres_check"]
    failures: list[str] = []
    if bm25_written:
        try:
            with _BM25_INDEX_LOCK:
                (bm25_remove_func or remove_from_trusted_bm25_index)(document_key)
        except Exception as exc:
            logger.error("compensation failed to clean bm25 for %s: %s", document_key, _log_detail(exc))
            failures.append("bm25")
    if vector_written:
        try:
            store = vector_store if vector_store is not None else trusted_vector_store(Settings())
            store.delete_document(document_key)
        except Exception as exc:
            logger.error("compensation failed to clean chroma for %s: %s", document_key, _log_detail(exc))
            failures.append("chroma")
    return failures


def reap_stale_jobs(
    db: Session,
    *,
    upload_dir: Path | None,
    settings: Settings | None = None,
    now: datetime | None = None,
    vector_store: Any = None,
    bm25_remove_func: Callable[[str], int] | None = None,
) -> list[str]:
    """Mark jobs stuck in a non-terminal state past the threshold as FAILED (BE-005).

    Only INDEXING jobs can have written index entries. Their document key is
    recomputed from the stored upload (``<job_id>_<name>`` in upload_dir), and
    the entries are removed as in compensate_document. Returns the reaped job IDs.
    """
    settings = settings or Settings()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.ingestion_stale_job_minutes)
    candidates = db.query(IngestionJob).filter(IngestionJob.status.in_(NON_TERMINAL_STATUSES)).all()
    stale = [job for job in candidates if _as_utc(job.started_at or job.created_at) < cutoff]
    reaped: list[str] = []
    for job in stale:
        with _INGEST_WRITE_LOCK:
            db.refresh(job)
            if job.status not in NON_TERMINAL_STATUSES:
                continue  # finished while we waited for the lock
            failures: list[str] = []
            if job.status == IngestionStatus.INDEXING.value:
                key = _upload_document_key(job.id, upload_dir)
                if key is None:
                    failures = ["unknown_document"]
                else:
                    failures = compensate_document(
                        db, key, vector_store=vector_store, vector_written=True, bm25_written=True,
                        bm25_remove_func=bm25_remove_func,
                    )
                    db.refresh(job)
            job.status = IngestionStatus.FAILED.value
            job.error_code = "STALE_JOB"
            job.error_message = SAFE_MESSAGES["STALE_JOB"] + (RECONCILIATION_SUFFIX if failures else "")
            job.needs_reconciliation = bool(failures)
            job.completed_at = now
            db.commit()
            logger.warning("reaped stale ingestion job=%s cleanup_failures=%s", job.id, failures or "none")
            reaped.append(job.id)
    return reaped


# --------------------------------------------------------------------------
# Chunk and metadata shaping
# --------------------------------------------------------------------------


def corpus_format_chunk(
    raw: dict[str, Any],
    position: int,
    key: str,
    checksum: str,
    case_title: str,
    court_level: str | None,
    year: int | None,
    source_url: str | None,
    text_source_type: str,
) -> dict[str, Any]:
    """Shape a chunk like the curated corpus chunk files (same Chroma/BM25 schema).

    Fields the upload does not supply (court name, decision date, offence
    family, legal regime) stay empty here. add_index_metadata later derives
    the legal regime from the cited statutes; the offence family is never
    inferred.
    """
    chunk_index = int(raw.get("chunk_index", position))
    heading_path = list(raw.get("heading_path") or [])
    heading = raw.get("section_heading") or " > ".join(heading_path) or None
    return {
        "chunk_id": f"{key}:chunk:{chunk_index:04d}",
        "document_id": key,
        "provider": ADMIN_PROVIDER,
        "source_document_id": checksum,
        "source_url": source_url,
        "case_title": case_title,
        "court": {"court_level": court_level} if court_level else {},
        "decision_date": None,
        "decision_year": year,
        "effective_offence_family": None,
        "effective_legal_regime": None,
        "chunk_index": chunk_index,
        # The index schema requires integer paragraphs; PostgreSQL stores the same value.
        "paragraph_start": int(raw.get("paragraph_start") or 0),
        "paragraph_end": int(raw.get("paragraph_end") or 0),
        "page_start": raw.get("page_start"),
        "page_end": raw.get("page_end"),
        "text_source_type": raw.get("text_source_type") or text_source_type,
        "raw_sha256": checksum,
        "normalizer_version": raw.get("normalizer_version"),
        "chunker_version": raw.get("chunker_version"),
        "chunk_text": raw.get("chunk_text") or raw["text"],
        "estimated_token_count": raw.get("estimated_token_count") or raw.get("token_count"),
        "heading_path": heading_path,
        "section_heading": heading[:SECTION_HEADING_MAX] if heading else None,
    }


def analytics_chunks(chunks: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """(chunk_index, chunk_id, text), the producer's chunk form."""
    return [(chunk["chunk_index"], chunk["chunk_id"], chunk["chunk_text"]) for chunk in chunks]


def add_index_metadata(chunks: list[dict[str, Any]], doc_type: str) -> None:
    """Add index_metadata_v1 fields and the derived legal regime to each chunk, before any write.

    The sections come from the producer's extractor (desired_sections), so they
    equal the document_sections rows produce_document writes in the same ingestion.
    """
    from backend.app.services.index_metadata import chunk_index_fields, derive_legal_regime

    pairs = set(desired_sections(analytics_chunks(chunks))[0])
    regime = derive_legal_regime(statute for statute, _ in pairs)
    for chunk in chunks:
        chunk.update(chunk_index_fields(doc_type, pairs, chunk["chunk_text"]))
        chunk["effective_legal_regime"] = regime


def chroma_metadatas(chunks: list[dict[str, Any]], provider: Any) -> list[dict[str, Any]]:
    """Chroma metadata exactly as build_vector_index writes it for the corpus."""
    from backend.app.services.embeddings.base import EmbeddingConfig
    from backend.app.services.vector_store import metadata_for_chroma
    from backend.scripts.build_vector_index import index_fingerprint

    config = getattr(provider, "config", None) or EmbeddingConfig()
    return [metadata_for_chroma(chunk, index_fingerprint(chunk, config)) for chunk in chunks]


def pg_chunk(chunk: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_index=chunk["chunk_index"],
        text=chunk["chunk_text"],
        chroma_id=chunk["chunk_id"],
        token_count=chunk["estimated_token_count"],
        page_start=chunk["page_start"],
        page_end=chunk["page_end"],
        paragraph_start=chunk["paragraph_start"],
        paragraph_end=chunk["paragraph_end"],
        section_heading=chunk["section_heading"],
    )


def trusted_vector_store(settings: Settings) -> Any:
    """Open the trusted-corpus Chroma collection for writing (created if missing).

    Ingestion and index builds are the only paths allowed to create the
    collection; read paths open it with create_if_missing=False.
    """
    from backend.app.services.vector_store import ChromaVectorStore, INDEX_VERSION

    persist_dir, collection_name = resolve_chroma_location(settings)
    return ChromaVectorStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
        collection_metadata={"index_version": INDEX_VERSION},
    )


def update_trusted_bm25_index(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_B, DEFAULT_INDEX_NAME, DEFAULT_K1
    from backend.scripts import build_lexical_index

    index = Bm25LexicalIndex(build_lexical_index.DEFAULT_PERSIST_DIR, DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
    return index.upsert_chunks(chunks)


def remove_from_trusted_bm25_index(document_key: str) -> int:
    from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, DEFAULT_B, DEFAULT_INDEX_NAME, DEFAULT_K1
    from backend.scripts import build_lexical_index

    index = Bm25LexicalIndex(build_lexical_index.DEFAULT_PERSIST_DIR, DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
    return index.remove_document(document_key)


def invalidate_retrieval_cache() -> None:
    try:
        from backend.app.api.query import clear_retrieval_service_cache
    except Exception:
        return
    clear_retrieval_service_cache()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _advance(db: Session, job: IngestionJob, status: IngestionStatus, progress: int, started: bool = False) -> None:
    job.status = status.value
    job.progress = progress
    if started:
        job.started_at = datetime.now(timezone.utc)
    db.commit()


def _default_parser() -> Callable[[str], dict[str, Any]]:
    from backend.app.services.document_parser import parse_document

    return parse_document


def _default_chunker() -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    from backend.app.services.chunker import chunk_document

    return chunk_document


def _default_embedder() -> Any:
    from backend.app.services.embeddings.base import EmbeddingConfig
    from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider

    return BgeM3EmbeddingProvider(EmbeddingConfig())


def _prepare_for_chunking(
    extracted: dict[str, Any],
    key: str,
    checksum: str,
    case_title: str,
    court_level: str | None,
    year: int | None,
    source_url: str | None,
) -> None:
    """Point the chunker at the admin document key so it emits corpus-format chunk IDs."""
    extracted["document_id"] = key
    metadata = extracted.setdefault("metadata", {})
    metadata.update(
        {
            "provider": ADMIN_PROVIDER,
            "source_document_id": checksum,
            "source_url": source_url,
            "case_title": case_title,
            "court": {"court_level": court_level} if court_level else None,
            "decision_year": year,
        }
    )


def _committed_document_exists(db: Session, key: str, checksum: str | None) -> bool:
    """Whether PostgreSQL already holds a committed document with this key or checksum."""
    condition = Document.source_document_key == key
    if checksum:
        condition = or_(condition, Document.checksum == checksum)
    return db.query(Document.id).filter(condition).first() is not None


def _content_checksum(extracted: dict[str, Any], file_path: str) -> str:
    if extracted.get("sha256"):
        return str(extracted["sha256"])
    path = Path(file_path)
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(str(extracted.get("text") or "").encode("utf-8")).hexdigest()


def _upload_document_key(job_id: str, upload_dir: Path | None) -> str | None:
    if upload_dir is None or not Path(upload_dir).is_dir():
        return None
    matches = sorted(Path(upload_dir).glob(f"{job_id}_*"))
    if len(matches) != 1:
        return None
    return admin_document_key(hashlib.sha256(matches[0].read_bytes()).hexdigest())


def _code_for(stage: str, exc: Exception) -> str:
    from backend.app.services.document_parser import DocumentParsingError

    if isinstance(exc, DocumentParsingError) and "no extractable" in str(exc).lower():
        return "PDF_NO_TEXT"
    return STAGE_ERROR_CODES.get(stage, "INGESTION_FAILED")


def _record_failure(db: Session, job_id: str, code: str, cleanup_failures: list[str]) -> None:
    try:
        db.rollback()
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if job is None:
            return
        job.status = IngestionStatus.FAILED.value
        job.error_code = code
        job.error_message = SAFE_MESSAGES[code] + (RECONCILIATION_SUFFIX if cleanup_failures else "")
        job.needs_reconciliation = bool(cleanup_failures)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        logger.error("could not record failure for ingestion job=%s: %s", job_id, _log_detail(exc))


def _invalidate(invalidator: Callable[[], None] | None) -> None:
    try:
        (invalidator or invalidate_retrieval_cache)()
    except Exception as exc:  # the document is committed; a stale cache is not a failure
        logger.warning("retrieval cache invalidation failed: %s", _log_detail(exc))


def _log_detail(exc: BaseException) -> str:
    """Exception type and message for logs, without SQL parameters or document text."""
    if isinstance(exc, SQLAlchemyError):
        original = getattr(exc, "orig", None)
        message = str(original if original is not None else type(exc).__name__).splitlines()[0]
    else:
        message = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {message[:300]}"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
