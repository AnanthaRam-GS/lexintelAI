"""Source attribution for ipc_bns_mapping rows; nullable change_type for non-CYTRAIN rows (step 19b).

Revision ID: 0011_ipc_bns_source
Revises: 0010_ncrb_section_labels
Create Date: 2026-10-26 00:00:00.000000

- ``source``: where a row comes from, one of ``CYTRAIN`` (the NCRB/CYTRAIN IPC-BNS correspondence table; every row
  before this revision, backfilled) or ``NCRB_CII_2024_T1A4`` (a correspondence printed in NCRB Crime in India 2024,
  Vol. I, Table 1A.4). NOT NULL after the backfill.
- ``source_page``: the printed table page for an NCRB row (NULL for CYTRAIN rows).
- ``change_type`` becomes nullable, but only a non-CYTRAIN row may leave it NULL (no source gives one; it is never
  guessed): ``ck_ipc_bns_mapping_change_type_source``.

Downgrade refuses while non-CYTRAIN rows exist (their change_type is NULL and cannot be restored to NOT NULL without
inventing a value). Delete them first; they reload from data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_ipc_bns_source"
down_revision: Union[str, None] = "0010_ncrb_section_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCES = ("CYTRAIN", "NCRB_CII_2024_T1A4")


def upgrade() -> None:
    op.add_column("ipc_bns_mapping", sa.Column("source", sa.String(length=40), nullable=True))
    op.add_column("ipc_bns_mapping", sa.Column("source_page", sa.Integer(), nullable=True))
    op.execute("UPDATE ipc_bns_mapping SET source = 'CYTRAIN' WHERE source IS NULL")
    op.alter_column("ipc_bns_mapping", "source", existing_type=sa.String(length=40), nullable=False)
    op.create_index("ix_ipc_bns_mapping_source", "ipc_bns_mapping", ["source"])
    allowed = ", ".join(f"'{value}'" for value in SOURCES)
    op.create_check_constraint("ck_ipc_bns_mapping_source", "ipc_bns_mapping", f"source IN ({allowed})")
    op.alter_column("ipc_bns_mapping", "change_type", existing_type=sa.String(length=50), nullable=True)
    op.create_check_constraint(
        "ck_ipc_bns_mapping_change_type_source", "ipc_bns_mapping", "change_type IS NOT NULL OR source <> 'CYTRAIN'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    remaining = bind.execute(sa.text("SELECT count(*) FROM ipc_bns_mapping WHERE source <> 'CYTRAIN'")).scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} non-CYTRAIN ipc_bns_mapping row(s) exist; their change_type is NULL. Delete them "
            "(DELETE FROM ipc_bns_mapping WHERE source <> 'CYTRAIN') before downgrading."
        )
    op.drop_constraint("ck_ipc_bns_mapping_change_type_source", "ipc_bns_mapping", type_="check")
    op.alter_column("ipc_bns_mapping", "change_type", existing_type=sa.String(length=50), nullable=False)
    op.drop_constraint("ck_ipc_bns_mapping_source", "ipc_bns_mapping", type_="check")
    op.drop_index("ix_ipc_bns_mapping_source", table_name="ipc_bns_mapping")
    op.drop_column("ipc_bns_mapping", "source_page")
    op.drop_column("ipc_bns_mapping", "source")
