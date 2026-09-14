"""Reusable legal document chunking service for backend ingestion."""

from __future__ import annotations

from typing import Any

from backend.scripts import process_judgment_corpus as judgment_processing


class DocumentChunkingError(RuntimeError):
    """Raised when parsed document content cannot be chunked."""


def chunk_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Chunk a parsed document using the frozen Phase 0 judgment chunker."""
    if not isinstance(document, dict):
        raise DocumentChunkingError("Parsed document must be a dictionary.")

    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise DocumentChunkingError("Parsed document contains no paragraphs to chunk.")

    entry = _entry_from_document(document)
    chunks = judgment_processing.chunk_blocks(entry, paragraphs)
    if not chunks:
        raise DocumentChunkingError("Chunking produced no chunks.")
    judgment_processing.validate_chunks(entry, paragraphs, chunks)
    return [_ingestion_chunk(chunk) for chunk in chunks]


def _entry_from_document(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") or {}
    document_id = document.get("document_id")
    if not document_id:
        raise DocumentChunkingError("Parsed document is missing document_id.")
    return {
        "document_id": document_id,
        "provider": metadata.get("provider") or "local_upload",
        "source_document_id": metadata.get("source_document_id") or document_id,
        "source_url": metadata.get("source_url"),
        "case_title": metadata.get("case_title") or document.get("source_file_name"),
        "court": metadata.get("court"),
        "decision_date": metadata.get("decision_date"),
        "decision_year": metadata.get("decision_year"),
        "effective_offence_family": metadata.get("effective_offence_family"),
        "effective_legal_regime": metadata.get("effective_legal_regime"),
        "text_source_type": metadata.get("text_source_type") or "pdf_native",
        "sha256": document.get("sha256"),
    }


def _ingestion_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        **chunk,
        "text": chunk["chunk_text"],
        "token_count": chunk["estimated_token_count"],
        "section_heading": " > ".join(chunk.get("heading_path") or []) or None,
    }
