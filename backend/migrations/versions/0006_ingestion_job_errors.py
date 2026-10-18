"""Ingestion job error code and reconciliation flag.

Revision ID: 0006_ingest_job_errors
Revises: 0005_corpus_keys
Create Date: 2026-10-18 00:00:00.000000

- ingestion_jobs.error_code: internal failure code (SEC-007). error_message
  now holds only a sanitized, user-safe message.
- ingestion_jobs.needs_reconciliation: set when compensating cleanup after a
  failed ingestion could not complete (BE-001), so the stores must be checked
  with verify_store_consistency.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_ingest_job_errors"
down_revision: Union[str, None] = "0005_corpus_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column(
        "ingestion_jobs",
        sa.Column("needs_reconciliation", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "needs_reconciliation")
    op.drop_column("ingestion_jobs", "error_code")
