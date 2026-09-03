"""Validation script for LegalAI Step 0.3 schema specification."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.dialects.postgresql import JSONB
from backend.app.db.models import (
    Base,
    Document,
    Chunk,
    DocumentSection,
    QueryHistory,
    User,
    IngestionJob,
    IpcBnsMapping,
    NcrbStat,
)

def test_schema():
    tables = Base.metadata.tables
    expected_tables = {
        "documents",
        "chunks",
        "document_sections",
        "query_history",
        "users",
        "ingestion_jobs",
        "ipc_bns_mapping",
        "ncrb_stats",
    }
    assert expected_tables.issubset(tables.keys()), f"Missing tables: {expected_tables - set(tables.keys())}"
    print("[PASS] All 8 tables present in Base.metadata")

    # 1. documents
    doc_cols = tables["documents"].columns
    expected_doc_cols = [
        "id", "doc_type", "case_name", "court_name", "court_level",
        "case_number", "decision_date", "year", "case_disposition",
        "conviction_status", "appeal_result", "source_url", "file_path",
        "checksum", "ingested_at",
    ]
    for col in expected_doc_cols:
        assert col in doc_cols, f"documents missing column: {col}"
    assert doc_cols["id"].primary_key, "documents.id is not PK"
    print("[PASS] documents columns and PK verified")

    # 2. chunks
    chunk_cols = tables["chunks"].columns
    expected_chunk_cols = [
        "id", "document_id", "chunk_index", "text", "chroma_id",
        "token_count", "page_start", "page_end", "paragraph_start",
        "paragraph_end", "section_heading",
    ]
    for col in expected_chunk_cols:
        assert col in chunk_cols, f"chunks missing column: {col}"
    assert not chunk_cols["document_id"].nullable, "chunks.document_id must not be nullable"
    print("[PASS] chunks columns and FK verified")

    # 3. document_sections
    sec_cols = tables["document_sections"].columns
    expected_sec_cols = ["id", "document_id", "statute", "section"]
    for col in expected_sec_cols:
        assert col in sec_cols, f"document_sections missing column: {col}"
    assert not sec_cols["document_id"].nullable, "document_sections.document_id must not be nullable"
    print("[PASS] document_sections columns and FK verified")

    # 4. query_history
    qh_cols = tables["query_history"].columns
    expected_qh_cols = [
        "id", "user_id", "session_id", "mode", "query_text",
        "response_json", "generation_backend", "created_at",
    ]
    for col in expected_qh_cols:
        assert col in qh_cols, f"query_history missing column: {col}"
    assert qh_cols["user_id"].nullable, "query_history.user_id must be nullable"
    assert isinstance(qh_cols["response_json"].type, JSONB), "query_history.response_json must be JSONB"
    print("[PASS] query_history columns, nullable user_id, and JSONB verified")

    # 5. users
    user_cols = tables["users"].columns
    expected_user_cols = ["id", "email", "hashed_password", "role", "created_at"]
    for col in expected_user_cols:
        assert col in user_cols, f"users missing column: {col}"
    user_constraints = [c.name for c in tables["users"].constraints]
    assert "uq_users_email" in user_constraints, "users missing uq_users_email constraint"
    assert "check_user_role" in user_constraints, "users missing check_user_role constraint"
    user_indexes = {idx.name: idx.unique for idx in tables["users"].indexes}
    assert "ix_users_email" in user_indexes and user_indexes["ix_users_email"], "users missing unique ix_users_email index"
    print("[PASS] users columns, unique constraint, role check, and unique index verified")

    # 6. ingestion_jobs
    job_cols = tables["ingestion_jobs"].columns
    expected_job_cols = [
        "id", "document_id", "status", "progress", "error_message",
        "created_at", "started_at", "completed_at",
    ]
    for col in expected_job_cols:
        assert col in job_cols, f"ingestion_jobs missing column: {col}"
    assert job_cols["document_id"].nullable, "ingestion_jobs.document_id must be nullable"
    print("[PASS] ingestion_jobs columns and nullable document_id verified")

    # 7. ipc_bns_mapping
    map_cols = tables["ipc_bns_mapping"].columns
    expected_map_cols = [
        "id", "ipc_section", "ipc_description", "bns_section",
        "bns_description", "change_type",
    ]
    for col in expected_map_cols:
        assert col in map_cols, f"ipc_bns_mapping missing column: {col}"
    print("[PASS] ipc_bns_mapping columns verified")

    # 8. ncrb_stats
    ncrb_cols = tables["ncrb_stats"].columns
    expected_ncrb_cols = [
        "id", "year", "state", "offense_category", "ipc_section",
        "case_count", "conviction_count", "acquittal_count",
    ]
    for col in expected_ncrb_cols:
        assert col in ncrb_cols, f"ncrb_stats missing column: {col}"
    print("[PASS] ncrb_stats columns verified")

    # ORM Relationships
    assert hasattr(Document, "chunks"), "Document missing chunks relationship"
    assert hasattr(Document, "document_sections"), "Document missing document_sections relationship"
    assert hasattr(Document, "ingestion_jobs"), "Document missing ingestion_jobs relationship"
    assert hasattr(User, "query_history"), "User missing query_history relationship"
    assert hasattr(Chunk, "document"), "Chunk missing document relationship"
    assert hasattr(DocumentSection, "document"), "DocumentSection missing document relationship"
    assert hasattr(QueryHistory, "user"), "QueryHistory missing user relationship"
    assert hasattr(IngestionJob, "document"), "IngestionJob missing document relationship"
    print("[PASS] All ORM relationships verified")

if __name__ == "__main__":
    test_schema()
    print("ALL SCHEMA ASSERTIONS PASSED SUCCESSFULLY!")
