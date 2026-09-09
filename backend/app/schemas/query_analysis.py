"""Typed legal query analysis schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SignalSource = Literal["explicit", "deterministic_inference", "model"]
SectionPredictionSource = Literal["deterministic_baseline", "classifier", "hybrid"]
SectionPredictionConfidence = Literal["high", "medium", "low"]
SectionPredictionRelationship = Literal["supports_explicit", "supplementary", "conflicts_with_explicit"]


class TextSpan(BaseModel):
    """Original-text span for an extracted query signal."""

    start: int
    end: int
    text: str


class ExtractedSignal(BaseModel):
    """Common signal metadata with provenance."""

    value: str
    normalized: str
    source: SignalSource
    span: TextSpan | None = None
    confidence: str = "high"


class StatuteSignal(ExtractedSignal):
    """Explicit statute mention."""

    canonical: str


class SectionSignal(ExtractedSignal):
    """Explicit statutory section mention."""

    section: str
    statute: str | None = None


class PredictedLegalSection(BaseModel):
    """Supplementary legal section candidate predicted from query signals."""

    statute: str
    section: str
    normalized_section: str
    score: float
    rank: int
    source: SectionPredictionSource
    confidence: SectionPredictionConfidence
    evidence: list[str] = Field(default_factory=list)
    prediction_version: str
    offence_family: str | None = None
    legal_regime: str | None = None
    relationship_to_explicit: SectionPredictionRelationship = "supplementary"
    warnings: list[str] = Field(default_factory=list)


class DateSignal(ExtractedSignal):
    """Date or legal-transition date phrase."""

    relation: Literal["before", "after", "on", "range", "unknown"]
    normalized_date: str | None = None
    normalized_range: list[str] = Field(default_factory=list)


class CourtSignal(ExtractedSignal):
    """Explicit court mention."""

    court_level: str | None = None
    court_name: str | None = None


class LegalRegimeEvidence(BaseModel):
    """Evidence returned by the deterministic legal-regime resolver."""

    explicit_codes: list[str] = Field(default_factory=list)
    explicit_sections: list[str] = Field(default_factory=list)
    detected_dates: list[str] = Field(default_factory=list)
    transition_terms: list[str] = Field(default_factory=list)


class LegalQueryAnalysis(BaseModel):
    """Structured deterministic analysis of a raw legal query."""

    original_query: str
    normalized_query: str
    explicit_statutes: list[StatuteSignal] = Field(default_factory=list)
    explicit_sections: list[SectionSignal] = Field(default_factory=list)
    explicit_legal_terms: list[ExtractedSignal] = Field(default_factory=list)
    dates: list[DateSignal] = Field(default_factory=list)
    date_ranges: list[DateSignal] = Field(default_factory=list)
    court_mentions: list[CourtSignal] = Field(default_factory=list)
    procedural_posture: list[ExtractedSignal] = Field(default_factory=list)
    offence_family_hints: list[ExtractedSignal] = Field(default_factory=list)
    legal_regime: str
    legal_regime_confidence: str
    legal_regime_evidence: LegalRegimeEvidence
    entities: list[ExtractedSignal] = Field(default_factory=list)
    predicted_sections: list[PredictedLegalSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analysis_version: str
