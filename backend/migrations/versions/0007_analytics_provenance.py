"""Provenance for produced analytics data; nullable NCRB case counts.

Revision ID: 0007_analytics_provenance
Revises: 0006_ingest_job_errors
Create Date: 2026-10-18 00:00:00.000000

- document_sections: mention_count, chunk_count, evidence_chunk_id and
  extraction_method record how each row was derived; (document_id, statute,
  section) becomes unique so the producer is idempotent.
- documents: outcome_evidence (JSON: per outcome field the rule that fired
  and the evidence chunk id) and outcome_method.
- ncrb_stats.case_count becomes nullable, and the "0" server defaults on
  case_count, conviction_count and acquittal_count are dropped: 41 source
  rows report no case count and none report convictions or acquittals, so
  storing 0 for them would fabricate data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_analytics_provenance"
down_revision: Union[str, None] = "0006_ingest_job_errors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT document_id, statute, section, count(*) FROM document_sections "
            "GROUP BY document_id, statute, section HAVING count(*) > 1"
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            f"Cannot make document_sections unique: {len(duplicates)} duplicated (document, statute, section) rows."
        )
    op.add_column("document_sections", sa.Column("mention_count", sa.Integer(), nullable=True))
    op.add_column("document_sections", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column("document_sections", sa.Column("evidence_chunk_id", sa.String(length=255), nullable=True))
    op.add_column("document_sections", sa.Column("extraction_method", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_document_sections_document_statute_section", "document_sections", ["document_id", "statute", "section"]
    )

    op.add_column("documents", sa.Column("outcome_evidence", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("outcome_method", sa.String(length=64), nullable=True))

    op.alter_column("ncrb_stats", "case_count", existing_type=sa.Integer(), nullable=True)
    # Drop the "0" server defaults: an unreported count must stay NULL.
    for column in ("case_count", "conviction_count", "acquittal_count"):
        op.alter_column("ncrb_stats", column, existing_type=sa.Integer(), server_default=None)


def downgrade() -> None:
    for column in ("case_count", "conviction_count", "acquittal_count"):
        op.alter_column("ncrb_stats", column, existing_type=sa.Integer(), server_default="0")
    nulls = op.get_bind().execute(sa.text("SELECT count(*) FROM ncrb_stats WHERE case_count IS NULL")).scalar()
    if nulls:
        raise RuntimeError(
            f"Cannot make ncrb_stats.case_count NOT NULL: {nulls} rows have no reported count. "
            "Delete or reload them first; writing 0 would fabricate counts."
        )
    op.alter_column("ncrb_stats", "case_count", existing_type=sa.Integer(), nullable=False)

    op.drop_column("documents", "outcome_method")
    op.drop_column("documents", "outcome_evidence")

    op.drop_constraint("uq_document_sections_document_statute_section", "document_sections", type_="unique")
    op.drop_column("document_sections", "extraction_method")
    op.drop_column("document_sections", "evidence_chunk_id")
    op.drop_column("document_sections", "chunk_count")
    op.drop_column("document_sections", "mention_count")
