"""Canonical deterministic NER foundation for LegalAI queries."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any
import re

from backend.app.schemas.legal_ner import (
    NER_SCHEMA_VERSION,
    CanonicalEntity,
    CanonicalEntityType,
    EntityProvenance,
    NERExtractionResult,
)
from backend.app.services.query_analysis import analyze_legal_query


CANONICAL_ENTITY_TYPES: tuple[str, ...] = (
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
)

LABEL_MAPPING: dict[str, str] = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "B-PER": "PERSON",
    "I-PER": "PERSON",
    "ORG": "ORGANIZATION",
    "ORGANISATION": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
    "B-ORG": "ORGANIZATION",
    "I-ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "LAW": "STATUTE",
    "ACT": "STATUTE",
    "STATUTE": "STATUTE",
    "SECTION": "SECTION",
    "COURT": "COURT",
    "DATE": "DATE",
    "CASE_CITATION": "CASE_CITATION",
    "CASE_NAME": "CASE_NAME",
    "LEGAL_PROCEDURE": "LEGAL_PROCEDURE",
    "PROCEDURE": "LEGAL_PROCEDURE",
    "OFFENCE": "OFFENCE",
    "OFFENSE": "OFFENCE",
    "LEGAL_ROLE": "LEGAL_ROLE",
    "ROLE": "LEGAL_ROLE",
    "POLICE_STATION": "POLICE_STATION",
    "PS": "POLICE_STATION",
    "FIR_NUMBER": "FIR_NUMBER",
    "FIR": "FIR_NUMBER",
}

CASE_CITATION_PATTERN = re.compile(r"\b(?:AIR\s+\d{4}\s+SC\s+\d+|\(\d{4}\)\s+\d+\s+SCC\s+\d+)\b", re.IGNORECASE)
FIR_NUMBER_PATTERN = re.compile(r"\bFIR\s+No\.?\s+\d+(?:\s+of\s+\d{4})?\b", re.IGNORECASE)
POLICE_STATION_PATTERN = re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\s+Police Station\b")
LEGAL_ROLE_PATTERN = re.compile(r"\b(?:accused|appellant|respondent|petitioner|complainant|victim|informant)\b", re.IGNORECASE)


class LegalNERModel:
    """Minimal model adapter contract for optional learned NER."""

    extractor = "legal_ner_model"
    model_name: str | None = None

    def extract(self, text: str) -> list[CanonicalEntity]:
        raise NotImplementedError


class DisabledLegalNERModel(LegalNERModel):
    """Safe default adapter used when learned NER is unavailable or disabled."""

    extractor = "disabled_legal_ner_model"
    model_name = None

    def extract(self, text: str) -> list[CanonicalEntity]:
        return []


@dataclass(frozen=True)
class TokenPrediction:
    token: str
    start_char: int | None
    end_char: int | None
    label: str
    confidence: float = 1.0
    is_special: bool = False


def canonical_entity_type(label: str) -> str | None:
    cleaned = label.strip()
    if not cleaned or cleaned == "O":
        return None
    if "-" in cleaned:
        prefix, suffix = cleaned.split("-", 1)
        if prefix in {"B", "I", "E", "S", "U", "L"}:
            cleaned = suffix
    return LABEL_MAPPING.get(cleaned.upper())


def extract_deterministic_entities(text: str) -> NERExtractionResult:
    started = perf_counter()
    analysis = analyze_legal_query(text)
    entities: list[CanonicalEntity] = []
    for statute in analysis.explicit_statutes:
        if statute.span:
            entities.append(make_entity(text, statute.span.start, statute.span.end, "STATUTE", "query_analysis.statute"))
    for section in analysis.explicit_sections:
        if section.span:
            start, end = expand_section_span(text, section.span.start, section.span.end)
            entities.append(make_entity(text, start, end, "SECTION", "query_analysis.section"))
    for court in analysis.court_mentions:
        if court.span:
            entities.append(make_entity(text, court.span.start, court.span.end, "COURT", "query_analysis.court"))
    for item in analysis.dates:
        if item.span:
            entities.append(make_entity(text, item.span.start, item.span.end, "DATE", "query_analysis.date"))
    for item in analysis.procedural_posture:
        if item.span:
            entities.append(make_entity(text, item.span.start, item.span.end, "LEGAL_PROCEDURE", "query_analysis.procedure"))
    for item in analysis.offence_family_hints:
        if item.span:
            entities.append(make_entity(text, item.span.start, item.span.end, "OFFENCE", "query_analysis.offence"))
    entities.extend(extract_pattern_entities(text))
    merged = merge_entities(entities)
    return NERExtractionResult(
        text=text,
        entities=merged,
        extractor="deterministic_legal_ner",
        model_name=None,
        latency_ms=round((perf_counter() - started) * 1000, 3),
        entity_count=len(merged),
    )


def make_entity(text: str, start: int, end: int, entity_type: str, extractor: str, confidence: float = 1.0) -> CanonicalEntity:
    span = text[start:end]
    provenance = EntityProvenance(source="deterministic", extractor=extractor, model_name=None, confidence=confidence)
    return CanonicalEntity(
        text=span,
        normalized_text=span.casefold(),
        entity_type=entity_type,  # type: ignore[arg-type]
        start_char=start,
        end_char=end,
        confidence=confidence,
        source="deterministic",
        extractor=extractor,
        model_name=None,
        provenance=[provenance],
    )


def expand_section_span(text: str, number_start: int, number_end: int) -> tuple[int, int]:
    prefix = text[max(0, number_start - 12) : number_start]
    match = re.search(r"(?:Sections?|Sec\.?|S\.?)\s*$", prefix, flags=re.IGNORECASE)
    return (max(0, number_start - len(match.group(0))), number_end) if match else (number_start, number_end)


def extract_pattern_entities(text: str) -> list[CanonicalEntity]:
    output: list[CanonicalEntity] = []
    for pattern, entity_type, extractor in (
        (CASE_CITATION_PATTERN, "CASE_CITATION", "deterministic.case_citation"),
        (FIR_NUMBER_PATTERN, "FIR_NUMBER", "deterministic.fir_number"),
        (POLICE_STATION_PATTERN, "POLICE_STATION", "deterministic.police_station"),
        (LEGAL_ROLE_PATTERN, "LEGAL_ROLE", "deterministic.legal_role"),
    ):
        for match in pattern.finditer(text):
            output.append(make_entity(text, match.start(), match.end(), entity_type, extractor))
    return output


def merge_entities(entities: list[CanonicalEntity]) -> list[CanonicalEntity]:
    exact: dict[tuple[int, int, str], CanonicalEntity] = {}
    for entity in sorted(entities, key=entity_sort_key):
        key = (entity.start_char, entity.end_char, entity.entity_type)
        if key in exact:
            exact[key] = combine_entities(exact[key], entity)
        else:
            exact[key] = entity
    selected: list[CanonicalEntity] = []
    for entity in sorted(exact.values(), key=entity_sort_key):
        overlapping = [kept for kept in selected if spans_overlap(entity, kept)]
        if not overlapping:
            selected.append(entity)
            continue
        if any(is_protected(kept) and not is_protected(entity) for kept in overlapping):
            continue
        for kept in overlapping:
            if should_replace(entity, kept):
                selected.remove(kept)
                selected.append(entity)
                break
    return sorted(selected, key=entity_sort_key)


def combine_entities(left: CanonicalEntity, right: CanonicalEntity) -> CanonicalEntity:
    provenance = (left.provenance or [provenance_from_entity(left)]) + (right.provenance or [provenance_from_entity(right)])
    source = "merged" if left.source != right.source else left.source
    return left.model_copy(update={"confidence": max(left.confidence, right.confidence), "source": source, "provenance": provenance})


def provenance_from_entity(entity: CanonicalEntity) -> EntityProvenance:
    return EntityProvenance(source=entity.source, extractor=entity.extractor, model_name=entity.model_name, confidence=entity.confidence)


def should_replace(candidate: CanonicalEntity, kept: CanonicalEntity) -> bool:
    if is_protected(candidate) and not is_protected(kept):
        return True
    if (candidate.end_char - candidate.start_char) != (kept.end_char - kept.start_char):
        return (candidate.end_char - candidate.start_char) > (kept.end_char - kept.start_char)
    if candidate.confidence != kept.confidence:
        return candidate.confidence > kept.confidence
    return str(candidate.entity_type) < str(kept.entity_type)


def is_protected(entity: CanonicalEntity) -> bool:
    return entity.source == "deterministic" and entity.entity_type in {"STATUTE", "SECTION"}


def spans_overlap(left: CanonicalEntity, right: CanonicalEntity) -> bool:
    return left.start_char < right.end_char and right.start_char < left.end_char


def entity_sort_key(entity: CanonicalEntity) -> tuple[int, int, str]:
    return (entity.start_char, -(entity.end_char - entity.start_char), str(entity.entity_type))


def reconstruct_bio_entities(tokens: list[TokenPrediction], text: str, extractor: str = "synthetic_token_classifier", model_name: str | None = None) -> list[CanonicalEntity]:
    output: list[CanonicalEntity] = []
    current: dict[str, Any] | None = None
    confidences: list[float] = []
    for token in tokens:
        if token.is_special or token.start_char is None or token.end_char is None:
            continue
        label_type = canonical_entity_type(token.label)
        prefix = token.label.split("-", 1)[0] if "-" in token.label else ("B" if label_type else "O")
        if not label_type:
            if current:
                output.append(finalize_token_entity(current, confidences, text, extractor, model_name))
                current = None
                confidences = []
            continue
        if current is None or prefix in {"B", "S", "U"} or current["entity_type"] != label_type:
            if current:
                output.append(finalize_token_entity(current, confidences, text, extractor, model_name))
            current = {"start": token.start_char, "end": token.end_char, "entity_type": label_type}
            confidences = [token.confidence]
        else:
            current["end"] = token.end_char
            confidences.append(token.confidence)
        if prefix in {"S", "U"} and current:
            output.append(finalize_token_entity(current, confidences, text, extractor, model_name))
            current = None
            confidences = []
    if current:
        output.append(finalize_token_entity(current, confidences, text, extractor, model_name))
    return merge_entities(output)


def finalize_token_entity(current: dict[str, Any], confidences: list[float], text: str, extractor: str, model_name: str | None) -> CanonicalEntity:
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    span = text[current["start"] : current["end"]]
    provenance = EntityProvenance(source="model", extractor=extractor, model_name=model_name, confidence=confidence)
    return CanonicalEntity(
        text=span,
        normalized_text=span.casefold(),
        entity_type=current["entity_type"],
        start_char=current["start"],
        end_char=current["end"],
        confidence=round(confidence, 6),
        source="model",
        extractor=extractor,
        model_name=model_name,
        provenance=[provenance],
    )


def exact_entity_metrics(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, Any]:
    pred_keys = Counter(entity_key(entity) for entity in predicted)
    gold_keys = Counter(entity_key(entity) for entity in gold)
    true_positive = sum((pred_keys & gold_keys).values())
    false_positive = sum((pred_keys - gold_keys).values())
    false_negative = sum((gold_keys - pred_keys).values())
    by_type: dict[str, dict[str, float | int]] = {}
    types = sorted({key[2] for key in pred_keys} | {key[2] for key in gold_keys})
    for entity_type in types:
        type_pred = [entity for entity in predicted if entity.entity_type == entity_type]
        type_gold = [entity for entity in gold if entity.entity_type == entity_type]
        by_type[entity_type] = metric_counts(type_pred, type_gold)
    return {"overall": metric_values(true_positive, false_positive, false_negative), "per_type": by_type}


def metric_counts(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> dict[str, float | int]:
    pred_keys = Counter(entity_key(entity) for entity in predicted)
    gold_keys = Counter(entity_key(entity) for entity in gold)
    return metric_values(sum((pred_keys & gold_keys).values()), sum((pred_keys - gold_keys).values()), sum((gold_keys - pred_keys).values()))


def metric_values(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6), "true_positive": tp, "false_positive": fp, "false_negative": fn}


def entity_key(entity: CanonicalEntity) -> tuple[int, int, str]:
    return (entity.start_char, entity.end_char, str(entity.entity_type))
