"""SQLAlchemy ORM models for LegalAI PostgreSQL database.

Defines the 8 core tables required for Step 0.3:
- documents
- chunks
- document_sections
- query_history
- users
- ingestion_jobs
- ipc_bns_mapping
- ncrb_stats
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    JSON,
)
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class Document(Base):
    """Corpus document metadata for judgments, statutes, and legal orders."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    doc_type = Column(String(50), nullable=False, index=True)
    case_name = Column(String(500), nullable=True)
    court_name = Column(String(255), nullable=True)
    court_level = Column(String(100), nullable=True, index=True)
    case_number = Column(String(100), nullable=True)
    decision_date = Column(Date, nullable=True)
    year = Column(Integer, nullable=True, index=True)
    case_disposition = Column(String(100), nullable=True)
    conviction_status = Column(String(100), nullable=True)
    appeal_result = Column(String(100), nullable=True)
    source_url = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    checksum = Column(String(64), nullable=True, index=True)
    ingested_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    document_sections = relationship(
        "DocumentSection",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    ingestion_jobs = relationship(
        "IngestionJob",
        back_populates="document",
    )


class Chunk(Base):
    """Text chunks extracted from documents for vector embedding and retrieval."""

    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    chroma_id = Column(String(255), nullable=True, index=True)
    token_count = Column(Integer, nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    paragraph_start = Column(Integer, nullable=True)
    paragraph_end = Column(Integer, nullable=True)
    section_heading = Column(String(255), nullable=True)

    # Relationship
    document = relationship("Document", back_populates="chunks")


class DocumentSection(Base):
    """Statutory sections referenced by or associated with a document."""

    __tablename__ = "document_sections"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statute = Column(String(255), nullable=False)
    section = Column(String(100), nullable=False, index=True)

    # Relationship
    document = relationship("Document", back_populates="document_sections")


class User(Base):
    """System users with role-based access for lawyers and administrators."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('public', 'lawyer', 'admin')",
            name="check_user_role",
        ),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_email", "email", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    email = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    email_verified = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    query_history = relationship("QueryHistory", back_populates="user")
    email_verification_tokens = relationship(
        "EmailVerificationToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    lawyer_applications = relationship(
        "LawyerVerificationApplication",
        back_populates="user",
        foreign_keys="LawyerVerificationApplication.user_id",
    )
    reviewed_lawyer_applications = relationship(
        "LawyerVerificationApplication",
        foreign_keys="LawyerVerificationApplication.reviewed_by",
    )


class EmailVerificationToken(Base):
    """Single-use email verification token metadata with hashed token storage."""

    __tablename__ = "email_verification_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="email_verification_tokens")


class LawyerVerificationApplication(Base):
    """Credential-review workflow for promoting registered public users to lawyer role."""

    __tablename__ = "lawyer_verification_applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED', 'RESUBMISSION_REQUIRED', 'SUSPENDED')",
            name="check_lawyer_application_status",
        ),
        Index("ix_lawyer_applications_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bar_council = Column(String(255), nullable=False)
    enrollment_number = Column(String(100), nullable=False, index=True)
    enrollment_year = Column(Integer, nullable=False)
    jurisdiction = Column(String(150), nullable=False)
    organization = Column(String(255), nullable=True)
    proof_file_name = Column(String(255), nullable=False)
    proof_content_type = Column(String(100), nullable=False)
    proof_storage_key = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING", server_default="PENDING", index=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    review_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="lawyer_applications", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by], overlaps="reviewed_lawyer_applications")


class QueryHistory(Base):
    """Audit log and history for professional and public legal queries."""

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id = Column(String(100), nullable=True, index=True)
    mode = Column(String(50), nullable=False)
    query_text = Column(Text, nullable=False)
    response_json = Column(JSON, nullable=True)
    generation_backend = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship
    user = relationship("User", back_populates="query_history")


class IngestionJob(Base):
    """Persistent ingestion tracking jobs for corpus documents."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'COMPLETED', 'FAILED')",
            name="check_ingestion_status",
        ),
    )

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        String(50),
        nullable=False,
        default="QUEUED",
        server_default="QUEUED",
        index=True,
    )
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    document = relationship("Document", back_populates="ingestion_jobs")


class IpcBnsMapping(Base):
    """Statutory mapping between Indian Penal Code (IPC) and Bharatiya Nyaya Sanhita (BNS)."""

    __tablename__ = "ipc_bns_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ipc_section = Column(String(100), nullable=False, index=True)
    ipc_description = Column(Text, nullable=False)
    bns_section = Column(String(50), nullable=True, index=True)
    bns_description = Column(Text, nullable=True)
    change_type = Column(String(50), nullable=False)


class NcrbStat(Base):
    """National Crime Records Bureau (NCRB) crime and disposal statistics."""

    __tablename__ = "ncrb_stats"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    year = Column(Integer, nullable=False, index=True)
    state = Column(String(100), nullable=False, index=True)
    offense_category = Column(String(150), nullable=False, index=True)
    ipc_section = Column(String(100), nullable=True, index=True)
    case_count = Column(Integer, nullable=False, default=0, server_default="0")
    conviction_count = Column(Integer, nullable=True, default=0, server_default="0")
    acquittal_count = Column(Integer, nullable=True, default=0, server_default="0")
