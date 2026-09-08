"""Typed schema for canonical LegalAI NER entities."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


NER_SCHEMA_VERSION = "legalai-ner-schema-v1"

CanonicalEntityType = Literal[
    "PERSON",
    "ORGANIZATION",
    "COURT",
    "LOCATION",
    "DATE",
    "STATUTE",
    "SECTION",
    "CASE_CITATION",
    "CASE_NAME",
    "LEGAL_PROCEDURE",
    "OFFENCE",
    "LEGAL_ROLE",
    "POLICE_STATION",
    "FIR_NUMBER",
]

EntitySource = Literal["deterministic", "model", "merged"]


class EntityProvenance(BaseModel):
    """Auditable source record for a canonical entity."""

    source: EntitySource
    extractor: str
    model_name: str | None = None
    confidence: float = 1.0


class CanonicalEntity(BaseModel):
    """Canonical NER entity with original-query character offsets."""

    text: str
    normalized_text: str
    entity_type: CanonicalEntityType
    start_char: int
    end_char: int
    confidence: float = 1.0
    source: EntitySource
    extractor: str
    model_name: str | None = None
    schema_version: str = NER_SCHEMA_VERSION
    canonical_id: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provenance: list[EntityProvenance] = Field(default_factory=list)


class NERExtractionResult(BaseModel):
    """NER extraction result with lightweight observability."""

    text: str
    entities: list[CanonicalEntity] = Field(default_factory=list)
    extractor: str
    model_name: str | None = None
    latency_ms: float = 0.0
    entity_count: int = 0
    schema_version: str = NER_SCHEMA_VERSION
