"""Lawyer verification API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LawyerApplicationStatus = Literal[
    "PENDING",
    "UNDER_REVIEW",
    "VERIFIED",
    "REJECTED",
    "RESUBMISSION_REQUIRED",
    "SUSPENDED",
]


class LawyerApplicationResponse(BaseModel):
    id: int
    user_id: int
    bar_council: str
    enrollment_number: str
    enrollment_year: int
    jurisdiction: str
    organization: str | None = None
    proof_file_name: str
    proof_content_type: str
    status: LawyerApplicationStatus
    submitted_at: datetime
    reviewed_at: datetime | None = None
    review_note: str | None = None


class LawyerApplicationEnvelope(BaseModel):
    application: LawyerApplicationResponse | None


class AdminLawyerApplicationResponse(LawyerApplicationResponse):
    applicant_email: str
    applicant_name: str | None = None
    reviewed_by: int | None = None


class AdminLawyerApplicationList(BaseModel):
    applications: list[AdminLawyerApplicationResponse]


class ReviewDecisionRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)
