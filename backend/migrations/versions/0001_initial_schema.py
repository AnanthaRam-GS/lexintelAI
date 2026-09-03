"""Initial PostgreSQL schema for LegalAI.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("case_name", sa.String(length=500), nullable=True),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("court_level", sa.String(length=100), nullable=True),
        sa.Column("case_number", sa.String(length=100), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("case_disposition", sa.String(length=100), nullable=True),
        sa.Column("conviction_status", sa.String(length=100), nullable=True),
        sa.Column("appeal_result", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_id", "documents", ["id"], unique=False)
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"], unique=False)
    op.create_index("ix_documents_court_level", "documents", ["court_level"], unique=False)
    op.create_index("ix_documents_year", "documents", ["year"], unique=False)
    op.create_index("ix_documents_checksum", "documents", ["checksum"], unique=False)

    # 2. chunks table
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chroma_id", sa.String(length=255), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("paragraph_start", sa.Integer(), nullable=True),
        sa.Column("paragraph_end", sa.Integer(), nullable=True),
        sa.Column("section_heading", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_id", "chunks", ["id"], unique=False)
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("ix_chunks_chroma_id", "chunks", ["chroma_id"], unique=False)

    # 3. document_sections table
    op.create_table(
        "document_sections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("statute", sa.String(length=255), nullable=False),
        sa.Column("section", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_sections_id", "document_sections", ["id"], unique=False)
    op.create_index("ix_document_sections_document_id", "document_sections", ["document_id"], unique=False)
    op.create_index("ix_document_sections_section", "document_sections", ["section"], unique=False)

    # 4. users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('lawyer', 'admin')", name="check_user_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 5. query_history table
    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generation_backend", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_history_id", "query_history", ["id"], unique=False)
    op.create_index("ix_query_history_user_id", "query_history", ["user_id"], unique=False)
    op.create_index("ix_query_history_session_id", "query_history", ["session_id"], unique=False)

    # 6. ingestion_jobs table
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="QUEUED", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'COMPLETED', 'FAILED')",
            name="check_ingestion_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_jobs_id", "ingestion_jobs", ["id"], unique=False)
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"], unique=False)
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"], unique=False)

    # 7. ipc_bns_mapping table
    op.create_table(
        "ipc_bns_mapping",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ipc_section", sa.String(length=50), nullable=False),
        sa.Column("ipc_description", sa.Text(), nullable=False),
        sa.Column("bns_section", sa.String(length=50), nullable=True),
        sa.Column("bns_description", sa.Text(), nullable=True),
        sa.Column("change_type", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ipc_bns_mapping_id", "ipc_bns_mapping", ["id"], unique=False)
    op.create_index("ix_ipc_bns_mapping_ipc_section", "ipc_bns_mapping", ["ipc_section"], unique=False)
    op.create_index("ix_ipc_bns_mapping_bns_section", "ipc_bns_mapping", ["bns_section"], unique=False)

    # 8. ncrb_stats table
    op.create_table(
        "ncrb_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=False),
        sa.Column("offense_category", sa.String(length=150), nullable=False),
        sa.Column("ipc_section", sa.String(length=50), nullable=True),
        sa.Column("case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conviction_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("acquittal_count", sa.Integer(), server_default="0", nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ncrb_stats_id", "ncrb_stats", ["id"], unique=False)
    op.create_index("ix_ncrb_stats_year", "ncrb_stats", ["year"], unique=False)
    op.create_index("ix_ncrb_stats_state", "ncrb_stats", ["state"], unique=False)
    op.create_index("ix_ncrb_stats_offense_category", "ncrb_stats", ["offense_category"], unique=False)
    op.create_index("ix_ncrb_stats_ipc_section", "ncrb_stats", ["ipc_section"], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order of foreign key dependencies
    op.drop_index("ix_ncrb_stats_ipc_section", table_name="ncrb_stats")
    op.drop_index("ix_ncrb_stats_offense_category", table_name="ncrb_stats")
    op.drop_index("ix_ncrb_stats_state", table_name="ncrb_stats")
    op.drop_index("ix_ncrb_stats_year", table_name="ncrb_stats")
    op.drop_index("ix_ncrb_stats_id", table_name="ncrb_stats")
    op.drop_table("ncrb_stats")

    op.drop_index("ix_ipc_bns_mapping_bns_section", table_name="ipc_bns_mapping")
    op.drop_index("ix_ipc_bns_mapping_ipc_section", table_name="ipc_bns_mapping")
    op.drop_index("ix_ipc_bns_mapping_id", table_name="ipc_bns_mapping")
    op.drop_table("ipc_bns_mapping")

    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_document_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")

    op.drop_index("ix_query_history_session_id", table_name="query_history")
    op.drop_index("ix_query_history_user_id", table_name="query_history")
    op.drop_index("ix_query_history_id", table_name="query_history")
    op.drop_table("query_history")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_document_sections_section", table_name="document_sections")
    op.drop_index("ix_document_sections_document_id", table_name="document_sections")
    op.drop_index("ix_document_sections_id", table_name="document_sections")
    op.drop_table("document_sections")

    op.drop_index("ix_chunks_chroma_id", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_chunks_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_checksum", table_name="documents")
    op.drop_index("ix_documents_year", table_name="documents")
    op.drop_index("ix_documents_court_level", table_name="documents")
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_index("ix_documents_id", table_name="documents")
    op.drop_table("documents")
