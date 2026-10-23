"""Document text extraction provenance (OCR fallback, RAG-005).

Revision ID: 0009_document_extraction
Revises: 0008_ncrb_bns_review
Create Date: 2026-10-23 00:00:00.000000

- documents.extraction_method: native | ocr | mixed. NULL for documents
  ingested before this revision (their method was not recorded; the corpus
  pipeline only ever used native text). No existing row is changed.
- documents.ocr_pages: JSON list of the page numbers read by OCR.
- documents.ocr_mean_confidence: word-weighted mean Tesseract confidence (0-100)
  over the OCR'd pages.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_document_extraction"
down_revision: Union[str, None] = "0008_ncrb_bns_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extraction_method", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("ocr_pages", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("ocr_mean_confidence", sa.Float(), nullable=True))
    op.create_check_constraint(
        "check_documents_extraction_method",
        "documents",
        "extraction_method IS NULL OR extraction_method IN ('native', 'ocr', 'mixed')",
    )


def downgrade() -> None:
    op.drop_constraint("check_documents_extraction_method", "documents", type_="check")
    op.drop_column("documents", "ocr_mean_confidence")
    op.drop_column("documents", "ocr_pages")
    op.drop_column("documents", "extraction_method")
