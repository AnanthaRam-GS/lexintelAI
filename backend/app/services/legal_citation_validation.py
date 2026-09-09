"""Structural citation and grounding validation for LegalAI answers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CitationValidationErrorCode(StrEnum):
    UNKNOWN_EVIDENCE_ID = "UNKNOWN_EVIDENCE_ID"
    ORPHAN_CITATION = "ORPHAN_CITATION"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    UNSUPPORTED_CASE_REFERENCE = "UNSUPPORTED_CASE_REFERENCE"
    DUPLICATE_MALFORMED_CITATION = "DUPLICATE_MALFORMED_CITATION"


class CitationValidationIssue(BaseModel):
    code: CitationValidationErrorCode
    message: str
    evidence_id: str | None = None
    claim_id: str | None = None


class CitationValidationResult(BaseModel):
    valid: bool
    issues: list[CitationValidationIssue] = Field(default_factory=list)


CASE_REFERENCE_KEYS = {"case_name", "court", "date", "source_url", "page_start", "page_end", "paragraph_start", "paragraph_end"}
CITED_CLAIM_TYPES = {"LEGAL_RULE", "PROCEDURAL_GUIDANCE", "CASE_LAW", "STATUTORY_REFERENCE", "FACTUAL_SUMMARY"}


def validate_legal_answer_citations(answer: Any, retrieval: Any) -> CitationValidationResult:
    evidence_by_id = {item.citation_id: item for item in retrieval.evidence}
    claim_ids = {claim.claim_id for claim in answer.claims}
    seen: set[tuple[str, str]] = set()
    issues: list[CitationValidationIssue] = []

    for citation in answer.citations:
        key = (citation.evidence_id, citation.claim_id)
        if key in seen:
            issues.append(
                CitationValidationIssue(
                    code=CitationValidationErrorCode.DUPLICATE_MALFORMED_CITATION,
                    message="Duplicate citation object for the same claim and evidence.",
                    evidence_id=citation.evidence_id,
                    claim_id=citation.claim_id,
                )
            )
        seen.add(key)
        if citation.claim_id not in claim_ids:
            issues.append(
                CitationValidationIssue(
                    code=CitationValidationErrorCode.ORPHAN_CITATION,
                    message="Citation references a claim that is not present in this answer.",
                    evidence_id=citation.evidence_id,
                    claim_id=citation.claim_id,
                )
            )
        evidence = evidence_by_id.get(citation.evidence_id)
        if evidence is None:
            issues.append(
                CitationValidationIssue(
                    code=CitationValidationErrorCode.UNKNOWN_EVIDENCE_ID,
                    message="Citation references evidence not present in the current retrieval result.",
                    evidence_id=citation.evidence_id,
                    claim_id=citation.claim_id,
                )
            )
            continue
        issues.extend(metadata_issues(citation, evidence))

    cited_pairs = {(citation.evidence_id, citation.claim_id) for citation in answer.citations}
    for claim in answer.claims:
        for citation in claim.citations:
            if (citation.evidence_id, citation.claim_id) not in cited_pairs:
                issues.append(
                    CitationValidationIssue(
                        code=CitationValidationErrorCode.ORPHAN_CITATION,
                        message="Claim contains a citation missing from the answer citation list.",
                        evidence_id=citation.evidence_id,
                        claim_id=claim.claim_id,
                    )
                )

    return CitationValidationResult(valid=not issues, issues=issues)


def metadata_issues(citation: Any, evidence: Any) -> list[CitationValidationIssue]:
    issues: list[CitationValidationIssue] = []
    metadata = citation.source_metadata or {}
    source = evidence.citation_metadata
    expected = source.model_dump(mode="json") if hasattr(source, "model_dump") else {}
    for key in CASE_REFERENCE_KEYS:
        if key in metadata and metadata[key] != expected.get(key):
            issues.append(
                CitationValidationIssue(
                    code=CitationValidationErrorCode.METADATA_MISMATCH,
                    message=f"Citation metadata field {key} does not match retrieved evidence.",
                    evidence_id=citation.evidence_id,
                    claim_id=citation.claim_id,
                )
            )
    if "case_name" in metadata and metadata["case_name"] and metadata["case_name"] != expected.get("case_name"):
        issues.append(
            CitationValidationIssue(
                code=CitationValidationErrorCode.UNSUPPORTED_CASE_REFERENCE,
                message="Case name was not derived from current evidence metadata.",
                evidence_id=citation.evidence_id,
                claim_id=citation.claim_id,
            )
        )
    if "source_url" in metadata and metadata["source_url"] and metadata["source_url"] != expected.get("source_url"):
        issues.append(
            CitationValidationIssue(
                code=CitationValidationErrorCode.UNSUPPORTED_CASE_REFERENCE,
                message="Source URL was not derived from current evidence metadata.",
                evidence_id=citation.evidence_id,
                claim_id=citation.claim_id,
            )
        )
    return issues


def validate_claim_grounding(claims: list[Any], valid_evidence_ids: set[str]) -> Any:
    from backend.app.services.legal_answer_generation import GroundingStatus

    if not claims:
        return GroundingStatus.UNGROUNDED
    requiring = [claim for claim in claims if str(claim.claim_type) in CITED_CLAIM_TYPES or getattr(claim.claim_type, "value", "") in CITED_CLAIM_TYPES]
    if not requiring:
        return GroundingStatus.STRUCTURALLY_GROUNDED
    grounded = 0
    for claim in requiring:
        valid = [citation for citation in claim.citations if citation.evidence_id in valid_evidence_ids]
        if valid:
            grounded += 1
    if grounded == len(requiring):
        return GroundingStatus.STRUCTURALLY_GROUNDED
    if grounded:
        return GroundingStatus.PARTIALLY_GROUNDED
    return GroundingStatus.UNGROUNDED
