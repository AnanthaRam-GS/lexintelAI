"""Add public registration and lawyer verification workflow.

Revision ID: 0003_reg_lawyer_verify
Revises: 0002_widen_ipc_section
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_reg_lawyer_verify"
down_revision: Union[str, None] = "0002_widen_ipc_section"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("check_user_role", "users", type_="check")
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("email_verified", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("is_active", sa.Integer(), server_default="1", nullable=False))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_check_constraint("check_user_role", "users", "role IN ('public', 'lawyer', 'admin')")

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_email_verification_tokens_id", "email_verification_tokens", ["id"], unique=False)
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"], unique=False)
    op.create_index("ix_email_verification_tokens_token_hash", "email_verification_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_verification_tokens_expires_at", "email_verification_tokens", ["expires_at"], unique=False)

    op.create_table(
        "lawyer_verification_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bar_council", sa.String(length=255), nullable=False),
        sa.Column("enrollment_number", sa.String(length=100), nullable=False),
        sa.Column("enrollment_year", sa.Integer(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=150), nullable=False),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("proof_file_name", sa.String(length=255), nullable=False),
        sa.Column("proof_content_type", sa.String(length=100), nullable=False),
        sa.Column("proof_storage_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED', 'RESUBMISSION_REQUIRED', 'SUSPENDED')",
            name="check_lawyer_application_status",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lawyer_verification_applications_id", "lawyer_verification_applications", ["id"], unique=False)
    op.create_index("ix_lawyer_verification_applications_user_id", "lawyer_verification_applications", ["user_id"], unique=False)
    op.create_index("ix_lawyer_verification_applications_enrollment_number", "lawyer_verification_applications", ["enrollment_number"], unique=False)
    op.create_index("ix_lawyer_verification_applications_status", "lawyer_verification_applications", ["status"], unique=False)
    op.create_index("ix_lawyer_verification_applications_reviewed_by", "lawyer_verification_applications", ["reviewed_by"], unique=False)
    op.create_index("ix_lawyer_applications_user_status", "lawyer_verification_applications", ["user_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lawyer_applications_user_status", table_name="lawyer_verification_applications")
    op.drop_index("ix_lawyer_verification_applications_reviewed_by", table_name="lawyer_verification_applications")
    op.drop_index("ix_lawyer_verification_applications_status", table_name="lawyer_verification_applications")
    op.drop_index("ix_lawyer_verification_applications_enrollment_number", table_name="lawyer_verification_applications")
    op.drop_index("ix_lawyer_verification_applications_user_id", table_name="lawyer_verification_applications")
    op.drop_index("ix_lawyer_verification_applications_id", table_name="lawyer_verification_applications")
    op.drop_table("lawyer_verification_applications")

    op.drop_index("ix_email_verification_tokens_expires_at", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_token_hash", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_user_id", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_id", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")

    op.drop_constraint("check_user_role", "users", type_="check")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "full_name")
    op.create_check_constraint("check_user_role", "users", "role IN ('lawyer', 'admin')")
