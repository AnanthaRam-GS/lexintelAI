"""Corpus ingestion service and job management for LegalAI.

Manages persistent ingestion jobs, state transitions across:
QUEUED -> EXTRACTING -> CHUNKING -> EMBEDDING -> INDEXING -> COMPLETED / FAILED
and coordinates document and chunk metadata persistence in PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import Chunk, Document, IngestionJob
from backend.app.db.session import SessionLocal, check_db_connection
from backend.app.models.ingest import (
    CorpusStatsResponse,
    CorpusTypeCount,
    IngestionStatus,
    IngestionStatusResponse,
)


def get_vector_store_status(settings: Settings | None = None) -> str:
    """Safely check vector-store availability without crashing."""
    try:
        import chromadb  # noqa: F401
        return "ready"
    except ImportError:
        return "unavailable (chromadb not installed)"
    except Exception as exc:
        return f"unavailable ({type(exc).__name__})"


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


def get_corpus_stats(db: Session) -> CorpusStatsResponse:
    """Return summary of documents and storage health."""
    total_docs = db.query(func.count(Document.id)).scalar() or 0
    last_updated = db.query(func.max(Document.ingested_at)).scalar()

    type_counts_raw = (
        db.query(Document.doc_type, func.count(Document.id))
        .group_by(Document.doc_type)
        .all()
    )
    by_type = [
        CorpusTypeCount(doc_type=row[0], count=row[1])
        for row in type_counts_raw
    ]

    is_db_ok, _ = check_db_connection()
    postgres_status = "connected" if is_db_ok else "unavailable"
    chroma_status = get_vector_store_status()

    return CorpusStatsResponse(
        total_documents=total_docs,
        last_updated=last_updated,
        by_type=by_type,
        postgres_status=postgres_status,
        chroma_status=chroma_status,
    )


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
) -> None:
    """Execute the ingestion state machine and persist output.

    State transitions:
    QUEUED -> EXTRACTING -> CHUNKING -> EMBEDDING -> INDEXING -> COMPLETED / FAILED
    """
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            return

        # 1. EXTRACTING
        job.status = IngestionStatus.EXTRACTING.value
        job.progress = 20
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        if parser_func is None:
            try:
                from backend.app.services.document_parser import parse_document  # type: ignore
                parser_func = parse_document
            except ImportError:
                raise RuntimeError(
                    "Ingestion blocked: Ananthu's shared document_parser service (Task 1.A.1) is not implemented."
                )

        extracted_data = parser_func(file_path)

        # 2. CHUNKING
        job.status = IngestionStatus.CHUNKING.value
        job.progress = 40
        db.commit()

        if chunker_func is None:
            try:
                from backend.app.services.chunker import chunk_document  # type: ignore
                chunker_func = chunk_document
            except ImportError:
                raise RuntimeError(
                    "Ingestion blocked: Ananthu's shared chunker service (Task 1.A.1) is not implemented."
                )

        chunks_data = chunker_func(extracted_data)
        if not isinstance(chunks_data, list) or len(chunks_data) == 0:
            raise ValueError("Chunking produced no chunks from document text.")

        # Create Document record
        doc = Document(
            doc_type=doc_type,
            case_name=case_name or Path(file_path).stem,
            court_level=court_level,
            year=year,
            source_url=source_url,
            file_path=file_path,
            checksum=checksum,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        job.document_id = doc.id
        db.commit()

        # 3. EMBEDDING
        job.status = IngestionStatus.EMBEDDING.value
        job.progress = 60
        db.commit()

        if embedding_provider is None:
            try:
                from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
                from backend.app.services.embeddings.base import EmbeddingConfig
                embedding_provider = BgeM3EmbeddingProvider(EmbeddingConfig())
            except Exception:
                raise RuntimeError(
                    "Ingestion blocked: BGE-M3 embedding service (Task 1.A.1) is not available."
                )

        texts = [c["text"] for c in chunks_data]
        vectors = embedding_provider.embed_documents(texts)

        # 4. INDEXING
        job.status = IngestionStatus.INDEXING.value
        job.progress = 80
        db.commit()

        # Save Chunks in PostgreSQL
        chroma_ids = []
        for idx, chunk_item in enumerate(chunks_data):
            chroma_id = f"doc:{doc.id}:chunk:{idx:04d}"
            chroma_ids.append(chroma_id)
            chunk_record = Chunk(
                document_id=doc.id,
                chunk_index=chunk_item.get("chunk_index", idx),
                text=chunk_item["text"],
                chroma_id=chroma_id,
                token_count=chunk_item.get("token_count"),
                page_start=chunk_item.get("page_start"),
                page_end=chunk_item.get("page_end"),
                paragraph_start=chunk_item.get("paragraph_start"),
                paragraph_end=chunk_item.get("paragraph_end"),
                section_heading=chunk_item.get("section_heading"),
            )
            db.add(chunk_record)

        db.commit()

        # Vector store indexing: MUST be executed using vector_store or ChromaVectorStore from shared vector_store.py
        if vector_store is None:
            try:
                from backend.app.services.vector_store import ChromaVectorStore, INDEX_VERSION
                s = Settings()
                vector_store = ChromaVectorStore(
                    persist_dir=Path(s.chroma_persist_dir),
                    collection_name=s.chroma_collection_name,
                    collection_metadata={"index_version": INDEX_VERSION},
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Ingestion blocked: Vector store indexing is unavailable ({exc})."
                )

        metadatas = [
            {
                "document_id": str(doc.id),
                "chunk_index": idx,
                "case_title": doc.case_name,
            }
            for idx in range(len(texts))
        ]
        upsert_res = vector_store.upsert_chunks(
            ids=chroma_ids,
            vectors=vectors,
            documents=texts,
            metadatas=metadatas,
        )
        if not upsert_res:
            raise RuntimeError("Vector store indexing produced no result.")

        # 5. COMPLETED - reached only after successful vector indexing
        job.status = IngestionStatus.COMPLETED.value
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        # Retrieve job in fresh transaction to record failure
        failed_job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if failed_job:
            failed_job.status = IngestionStatus.FAILED.value
            failed_job.error_message = str(exc)
            failed_job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
