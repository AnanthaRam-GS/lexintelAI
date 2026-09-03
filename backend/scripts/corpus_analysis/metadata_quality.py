"""Deterministic metadata completeness and provenance scoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_WEIGHTS = {
    "source_document_id": 0.14,
    "source_url": 0.14,
    "case_name": 0.1,
    "court_name": 0.08,
    "court_level": 0.08,
    "year": 0.08,
    "raw_file_path": 0.1,
    "sha256": 0.14,
    "file_size_bytes": 0.08,
    "mime_type": 0.04,
    "attribution_required": 0.02,
}


@dataclass(frozen=True)
class MetadataQualityAssessment:
    score: float
    missing_fields: list[str]
    warnings: list[str]


def assess_metadata_quality(record: dict[str, Any], repo_root: Path | None = None) -> MetadataQualityAssessment:
    missing: list[str] = []
    score = 0.0
    for field, weight in REQUIRED_WEIGHTS.items():
        value = record.get(field)
        if value is None or value == "" or value == "unknown":
            missing.append(field)
        else:
            score += weight
    warnings: list[str] = []
    raw_file_path = record.get("raw_file_path")
    if repo_root is not None and raw_file_path and not (repo_root / str(raw_file_path)).exists():
        warnings.append("raw_file_missing")
        score -= 0.08
    if record.get("file_size_bytes") == 0:
        warnings.append("zero_byte_file")
        score -= 0.2
    score = max(0.0, min(1.0, round(score, 3)))
    return MetadataQualityAssessment(score=score, missing_fields=missing, warnings=warnings)

