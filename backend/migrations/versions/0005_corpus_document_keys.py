"""Unique document checksum, source document key, and token_hash drift fix.

Revision ID: 0005_corpus_keys
Revises: 0004_email_otp
Create Date: 2026-10-17 00:00:00.000000

- documents.checksum becomes unique (DATA-003). Upgrade refuses to run while
  duplicate checksums exist instead of silently dropping rows.
- documents.source_document_key (e.g. ``indian_kanoon:<id>``) is added,
  unique where not null, so curated documents join to their Chroma and BM25
  entries.
- BE-006: migration 0003 created both a unique constraint and a unique index
  on email_verification_tokens.token_hash. The model declares only the
  index, so the redundant constraint is dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_corpus_keys"
down_revision: Union[str, None] = "0004_email_otp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT checksum, count(*) AS copies FROM documents WHERE checksum IS NOT NULL "
            "GROUP BY checksum HAVING count(*) > 1 ORDER BY count(*) DESC, checksum"
        )
    ).fetchall()
    if duplicates:
        extra_rows = sum(row.copies - 1 for row in duplicates)
        listed = ", ".join(f"{row.checksum} x{row.copies}" for row in duplicates[:10])
        raise RuntimeError(
            "Cannot make documents.checksum unique: "
            f"{len(duplicates)} checksum value(s) are duplicated ({extra_rows} extra row(s)): {listed}. "
            "Remove duplicate documents first (docs/reconciliation/EXECUTION_RUNBOOK.md)."
        )

    op.drop_index("ix_documents_checksum", table_name="documents")
    op.create_index("ix_documents_checksum", "documents", ["checksum"], unique=True)

    op.add_column("documents", sa.Column("source_document_key", sa.String(length=255), nullable=True))
    op.create_index(
        "uq_documents_source_document_key",
        "documents",
        ["source_document_key"],
        unique=True,
        postgresql_where=sa.text("source_document_key IS NOT NULL"),
    )

    op.drop_constraint("email_verification_tokens_token_hash_key", "email_verification_tokens", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("email_verification_tokens_token_hash_key", "email_verification_tokens", ["token_hash"])

    op.drop_index("uq_documents_source_document_key", table_name="documents")
    op.drop_column("documents", "source_document_key")

    op.drop_index("ix_documents_checksum", table_name="documents")
    op.create_index("ix_documents_checksum", "documents", ["checksum"], unique=False)
