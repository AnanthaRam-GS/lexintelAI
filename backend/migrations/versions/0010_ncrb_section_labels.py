"""NCRB statute-qualified section labels for filtering (step 15b).

Revision ID: 0010_ncrb_section_labels
Revises: 0009_document_extraction
Create Date: 2026-10-23 00:00:00.000000

- ncrb_stats.ipc_section_labels / bns_section_labels: JSON lists such as
  ["IPC 305", "IPC 306"], parsed from the printed ipc_section / bns_section
  text (kept unchanged) with the document_sections section form
  (backend/app/services/ncrb_sections.py). Filled by load_ncrb.py; NULL until
  the next load, and NULL when no parseable section is printed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_ncrb_section_labels"
down_revision: Union[str, None] = "0009_document_extraction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ncrb_stats", sa.Column("ipc_section_labels", sa.JSON(), nullable=True))
    op.add_column("ncrb_stats", sa.Column("bns_section_labels", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("ncrb_stats", "bns_section_labels")
    op.drop_column("ncrb_stats", "ipc_section_labels")
