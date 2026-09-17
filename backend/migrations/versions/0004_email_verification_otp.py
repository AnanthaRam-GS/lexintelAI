"""Add hashed email verification OTP records.

Revision ID: 0004_email_otp
Revises: 0003_reg_lawyer_verify
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_email_otp"
down_revision: Union[str, None] = "0003_reg_lawyer_verify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_verification_otps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_verification_otps_id", "email_verification_otps", ["id"], unique=False)
    op.create_index("ix_email_verification_otps_user_id", "email_verification_otps", ["user_id"], unique=False)
    op.create_index("ix_email_verification_otps_otp_hash", "email_verification_otps", ["otp_hash"], unique=False)
    op.create_index("ix_email_verification_otps_expires_at", "email_verification_otps", ["expires_at"], unique=False)
    op.create_index("ix_email_verification_otps_created_at", "email_verification_otps", ["created_at"], unique=False)
    op.create_index("ix_email_verification_otps_user_active", "email_verification_otps", ["user_id", "consumed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_verification_otps_user_active", table_name="email_verification_otps")
    op.drop_index("ix_email_verification_otps_created_at", table_name="email_verification_otps")
    op.drop_index("ix_email_verification_otps_expires_at", table_name="email_verification_otps")
    op.drop_index("ix_email_verification_otps_otp_hash", table_name="email_verification_otps")
    op.drop_index("ix_email_verification_otps_user_id", table_name="email_verification_otps")
    op.drop_index("ix_email_verification_otps_id", table_name="email_verification_otps")
    op.drop_table("email_verification_otps")
