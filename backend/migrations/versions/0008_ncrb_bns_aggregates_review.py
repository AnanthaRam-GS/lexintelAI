"""NCRB BNS sections and aggregate flag; analytics review state on documents.

Revision ID: 0008_ncrb_bns_review
Revises: 0007_analytics_provenance
Create Date: 2026-10-18 00:00:00.000000

- ncrb_stats.bns_section: NCRB Table 1A.4 reports BNS heads (4,610 rows) next
  to IPC heads; they were previously dropped by schema design.
- ncrb_stats.is_aggregate / aggregate_type: state/UT/all-India total rows and
  the table's own "(Total ...)" / "Total ..." heads, so sums can exclude them.
- documents.review_status / review_decision / reviewed_by / reviewed_at:
  human review of produced sections and outcomes. The producer never
  overwrites a REVIEWED document.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_ncrb_bns_review"
down_revision: Union[str, None] = "0007_analytics_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ncrb_stats", sa.Column("bns_section", sa.String(length=100), nullable=True))
    op.add_column("ncrb_stats", sa.Column("is_aggregate", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("ncrb_stats", sa.Column("aggregate_type", sa.String(length=32), nullable=True))
    op.create_index("ix_ncrb_stats_bns_section", "ncrb_stats", ["bns_section"], unique=False)
    op.create_index("ix_ncrb_stats_is_aggregate", "ncrb_stats", ["is_aggregate"], unique=False)

    op.add_column("documents", sa.Column("review_status", sa.String(length=20), server_default="UNREVIEWED", nullable=False))
    op.add_column("documents", sa.Column("review_decision", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("reviewed_by", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("check_documents_review_status", "documents", "review_status IN ('UNREVIEWED', 'REVIEWED')")
    op.create_check_constraint(
        "check_documents_review_decision",
        "documents",
        "review_decision IS NULL OR review_decision IN ('CONFIRMED', 'CORRECTED', 'REJECTED')",
    )


def downgrade() -> None:
    op.drop_constraint("check_documents_review_decision", "documents", type_="check")
    op.drop_constraint("check_documents_review_status", "documents", type_="check")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")
    op.drop_column("documents", "review_decision")
    op.drop_column("documents", "review_status")

    op.drop_index("ix_ncrb_stats_is_aggregate", table_name="ncrb_stats")
    op.drop_index("ix_ncrb_stats_bns_section", table_name="ncrb_stats")
    op.drop_column("ncrb_stats", "aggregate_type")
    op.drop_column("ncrb_stats", "is_aggregate")
    op.drop_column("ncrb_stats", "bns_section")
