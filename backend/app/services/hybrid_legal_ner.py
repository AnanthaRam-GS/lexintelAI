"""Hybrid merge policy for deterministic and learned LegalAI NER entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schemas.legal_ner import CanonicalEntity, EntityProvenance


PROTECTED_DETERMINISTIC_TYPES = {
    "STATUTE",
    "SECTION",
    "LEGAL_ROLE",
    "POLICE_STATION",
    "FIR_NUMBER",
    "LEGAL_PROCEDURE",
}

LEARNED_PREFERRED_TYPES = {
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "CASE_NAME",
}

SHARED_TYPES = {
    "COURT",
    "DATE",
    "OFFENCE",
    "CASE_CITATION",
}

TYPE_PRIORITY = {
    "SECTION": 100,
    "STATUTE": 95,
    "FIR_NUMBER": 90,
    "POLICE_STATION": 88,
    "LEGAL_PROCEDURE": 85,
    "LEGAL_ROLE": 80,
    "CASE_CITATION": 75,
    "CASE_NAME": 72,
    "COURT": 70,
    "DATE": 65,
    "OFFENCE": 60,
    "PERSON": 55,
    "ORGANIZATION": 50,
    "LOCATION": 45,
}

DEFAULT_MIN_CONFIDENCE = 0.7
DEFAULT_NER_MODE = "deterministic"
ALLOWED_NER_MODES = {"deterministic", "learned", "hybrid"}


@dataclass(frozen=True)
class HybridMergeConfig:
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    mode: str = DEFAULT_NER_MODE
    allow_shared_boundary_improvement: bool = True


@dataclass
class HybridMergeDiagnostics:
    deterministic_input_count: int = 0
    learned_input_count: int = 0
    learned_below_threshold: int = 0
    deterministic_protected_count: int = 0
    learned_suppressed_due_to_protected_overlap: int = 0
    learned_inserted_count: int = 0
    exact_duplicates_removed: int = 0
    same_span_conflicts: int = 0
    overlap_conflicts: int = 0
    protected_conflicts: list[dict[str, str | int | float]] = field(default_factory=list)
    suppressions: list[dict[str, str | int | float]] = field(default_factory=list)


@dataclass
class HybridMergeResult:
    entities: list[CanonicalEntity]
    diagnostics: HybridMergeDiagnostics


def merge_hybrid_entities(
    deterministic_entities: list[CanonicalEntity],
    learned_entities: list[CanonicalEntity],
    config: HybridMergeConfig | None = None,
) -> HybridMergeResult:
    cfg = config or HybridMergeConfig()
    if cfg.mode not in ALLOWED_NER_MODES:
        raise ValueError(f"unsupported legal NER mode: {cfg.mode}")
    diagnostics = HybridMergeDiagnostics(
        deterministic_input_count=len(deterministic_entities),
        learned_input_count=len(learned_entities),
        deterministic_protected_count=sum(1 for entity in deterministic_entities if is_protected(entity)),
    )
    if cfg.mode == "deterministic":
        return HybridMergeResult(sort_entities(dedupe_exact(deterministic_entities, diagnostics)), diagnostics)
    if cfg.mode == "learned":
        accepted = [entity for entity in learned_entities if above_threshold(entity, cfg, diagnostics)]
        return HybridMergeResult(sort_entities(dedupe_exact(accepted, diagnostics)), diagnostics)

    merged = dedupe_exact(deterministic_entities, diagnostics)
    for learned in sort_entities(learned_entities):
        if not above_threshold(learned, cfg, diagnostics):
            continue
        duplicate = find_exact_duplicate(learned, merged)
        if duplicate:
            combine_provenance(duplicate, learned)
            diagnostics.exact_duplicates_removed += 1
            continue
        same_span_conflicts = [entity for entity in merged if same_span(entity, learned)]
        if same_span_conflicts:
            diagnostics.same_span_conflicts += 1
            if should_replace_same_span(learned, same_span_conflicts[0]):
                merged.remove(same_span_conflicts[0])
                merged.append(mark_merged(learned, same_span_conflicts[0]))
                diagnostics.learned_inserted_count += 1
            else:
                record_suppression(diagnostics, learned, same_span_conflicts[0], "same_span_lower_priority")
            continue
        overlaps = [entity for entity in merged if spans_overlap(entity, learned)]
        if overlaps:
            diagnostics.overlap_conflicts += 1
            protected = [entity for entity in overlaps if is_protected(entity)]
            if protected:
                diagnostics.learned_suppressed_due_to_protected_overlap += 1
                record_suppression(diagnostics, learned, protected[0], "protected_overlap")
                diagnostics.protected_conflicts.append(conflict_record(learned, protected[0], "protected_overlap"))
                continue
            if can_improve_shared_boundary(learned, overlaps, cfg):
                for entity in overlaps:
                    merged.remove(entity)
                merged.append(mark_merged(learned, overlaps[0]))
                diagnostics.learned_inserted_count += 1
                continue
            record_suppression(diagnostics, learned, overlaps[0], "overlap_conflict")
            continue
        if str(learned.entity_type) in LEARNED_PREFERRED_TYPES | SHARED_TYPES:
            merged.append(learned)
            diagnostics.learned_inserted_count += 1
        else:
            record_suppression(diagnostics, learned, learned, "unaccepted_learned_type")
    return HybridMergeResult(sort_entities(dedupe_exact(merged, diagnostics)), diagnostics)


def above_threshold(entity: CanonicalEntity, config: HybridMergeConfig, diagnostics: HybridMergeDiagnostics) -> bool:
    if entity.confidence >= config.min_confidence:
        return True
    diagnostics.learned_below_threshold += 1
    return False


def is_protected(entity: CanonicalEntity) -> bool:
    return entity.source == "deterministic" and str(entity.entity_type) in PROTECTED_DETERMINISTIC_TYPES


def same_span(left: CanonicalEntity, right: CanonicalEntity) -> bool:
    return left.start_char == right.start_char and left.end_char == right.end_char


def spans_overlap(left: CanonicalEntity, right: CanonicalEntity) -> bool:
    return left.start_char < right.end_char and right.start_char < left.end_char


def should_replace_same_span(candidate: CanonicalEntity, existing: CanonicalEntity) -> bool:
    if is_protected(existing):
        return False
    return TYPE_PRIORITY.get(str(candidate.entity_type), 0) > TYPE_PRIORITY.get(str(existing.entity_type), 0)


def can_improve_shared_boundary(candidate: CanonicalEntity, overlaps: list[CanonicalEntity], config: HybridMergeConfig) -> bool:
    if not config.allow_shared_boundary_improvement or str(candidate.entity_type) not in SHARED_TYPES:
        return False
    return len(overlaps) == 1 and str(overlaps[0].entity_type) == str(candidate.entity_type)


def find_exact_duplicate(entity: CanonicalEntity, entities: list[CanonicalEntity]) -> CanonicalEntity | None:
    for existing in entities:
        if same_span(existing, entity) and existing.entity_type == entity.entity_type:
            return existing
    return None


def combine_provenance(target: CanonicalEntity, source: CanonicalEntity) -> None:
    target.provenance.extend(source.provenance or [provenance_from_entity(source)])


def mark_merged(entity: CanonicalEntity, replaced: CanonicalEntity) -> CanonicalEntity:
    provenance = (replaced.provenance or [provenance_from_entity(replaced)]) + (entity.provenance or [provenance_from_entity(entity)])
    return entity.model_copy(update={"source": "merged", "provenance": provenance})


def provenance_from_entity(entity: CanonicalEntity) -> EntityProvenance:
    return EntityProvenance(source=entity.source, extractor=entity.extractor, model_name=entity.model_name, confidence=entity.confidence)


def record_suppression(diagnostics: HybridMergeDiagnostics, learned: CanonicalEntity, existing: CanonicalEntity, reason: str) -> None:
    diagnostics.suppressions.append(conflict_record(learned, existing, reason))


def conflict_record(learned: CanonicalEntity, existing: CanonicalEntity, reason: str) -> dict[str, str | int | float]:
    return {
        "reason": reason,
        "learned_text": learned.text,
        "learned_type": str(learned.entity_type),
        "learned_start": learned.start_char,
        "learned_end": learned.end_char,
        "learned_confidence": learned.confidence,
        "existing_text": existing.text,
        "existing_type": str(existing.entity_type),
        "existing_start": existing.start_char,
        "existing_end": existing.end_char,
    }


def dedupe_exact(entities: list[CanonicalEntity], diagnostics: HybridMergeDiagnostics) -> list[CanonicalEntity]:
    output: list[CanonicalEntity] = []
    for entity in sort_entities(entities):
        duplicate = find_exact_duplicate(entity, output)
        if duplicate:
            combine_provenance(duplicate, entity)
            diagnostics.exact_duplicates_removed += 1
        else:
            output.append(entity)
    return output


def sort_entities(entities: list[CanonicalEntity]) -> list[CanonicalEntity]:
    return sorted(entities, key=lambda entity: (entity.start_char, -(entity.end_char - entity.start_char), str(entity.entity_type)))
