"""Prepare and update the offline human quality audit for bulk judgments."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest, write_manifest_atomic  # noqa: E402
from backend.scripts.generate_judgment_review_report import clean_text_preview  # noqa: E402
from backend.scripts.pdf_text_extraction import extract_pdf_text  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "bulk_20260904_000000_stagea"
RUN_ROOT = REPO_ROOT / "data/processed/acquisition_runs" / RUN_ID
BULK_CANDIDATES = RUN_ROOT / "candidates.json"
SAMPLE_MANIFEST = REPO_ROOT / "data/structured/manifests/bulk_quality_audit_sample.json"
SUMMARY_MANIFEST = REPO_ROOT / "data/structured/manifests/bulk_quality_audit_summary.json"
RAG_DECISIONS_MANIFEST = REPO_ROOT / "data/structured/manifests/bulk_quality_audit_rag_decisions.json"
REVIEW_PACKET = REPO_ROOT / "docs/BULK_CORPUS_QUALITY_AUDIT_REVIEW.md"
SUMMARY_DOC = REPO_ROOT / "docs/BULK_CORPUS_QUALITY_AUDIT.md"
SAMPLE_SIZE = 50
SAMPLING_VERSION = "bulk-quality-audit-stratified-v1"
RANDOM_SEED = "legalai-phase0-step0.4l"
PREVIEW_LIMIT = 1800
OFFENCE_FAMILIES = {
    "homicide",
    "hurt_and_assault",
    "theft_and_robbery",
    "cheating_and_fraud",
    "criminal_breach_of_trust",
    "kidnapping",
    "sexual_offences",
    "dowry_and_domestic_cruelty",
    "conspiracy_common_intention",
    "narcotics_related",
    "other",
}
LEGAL_REGIMES = {"ipc_crpc", "bns_bnss", "mixed_or_transition", "unknown"}
TEXT_SUFFIXES = {".html", ".htm", ".txt", ".json"}
REVIEWABLE_STATUSES = {"validated", "needs_review"}
REVIEW_ENUMS = {
    "criminal_relevance": {"correct", "incorrect", "uncertain"},
    "document_type": {"judgment", "non_judgment", "uncertain"},
    "offence_family_review": {"confirmed", "corrected", "uncertain"},
    "legal_regime_review": {"confirmed", "corrected", "uncertain"},
    "court_metadata_review": {"correct", "corrected", "uncertain"},
    "date_metadata_review": {"correct", "corrected", "uncertain"},
    "text_quality": {"usable", "degraded", "unusable"},
    "duplicate_or_noise": {"no", "duplicate", "irrelevant_noise", "provider_wrapper_only", "other"},
    "rag_suitability": {"accept", "reject", "needs_review"},
}
PROTECTED_FIELDS = {
    "source_document_id",
    "canonical_record_id",
    "source_url",
    "source_provider",
    "raw_file_path",
    "sha256",
    "mime_type",
    "file_size_bytes",
    "attribution_required",
    "attribution_text",
    "automated_status",
    "automated_decision",
    "offence_family_automated",
    "legal_regime_automated",
    "court_automated",
    "judgment_year",
    "judgment_date",
}


class AuditError(ValueError):
    """Raised for invalid audit generation or review commands."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def reviewable_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("status") in REVIEWABLE_STATUSES]


def stable_key(record: dict[str, Any], salt: str = "") -> str:
    parts = [
        RANDOM_SEED,
        salt,
        str(record.get("source_document_id") or ""),
        str(record.get("local_id") or ""),
        str(record.get("query_id") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def sorted_records(records: Iterable[dict[str, Any]], salt: str = "") -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: stable_key(record, salt))


def pick_first(
    records: list[dict[str, Any]],
    selected_ids: set[str],
    predicate: Any,
    reason: str,
    reasons: dict[str, list[str]],
) -> bool:
    for record in sorted_records(records, reason):
        source_id = str(record.get("source_document_id"))
        if source_id in selected_ids or not predicate(record):
            continue
        selected_ids.add(source_id)
        reasons[source_id].append(reason)
        return True
    return False


def allocate_sample(records: list[dict[str, Any]], target: int = SAMPLE_SIZE) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    selected_ids: set[str] = set()
    reasons: dict[str, list[str]] = defaultdict(list)

    for family in sorted({str(r.get("offence_family")) for r in records if r.get("offence_family")}):
        pick_first(records, selected_ids, lambda r, family=family: r.get("offence_family") == family, f"minimum_offence_family:{family}", reasons)

    for regime in sorted({str(r.get("legal_regime") or "unknown") for r in records}):
        pick_first(records, selected_ids, lambda r, regime=regime: str(r.get("legal_regime") or "unknown") == regime, f"minimum_legal_regime:{regime}", reasons)

    for track in sorted({str(r.get("temporal_track") or "unknown") for r in records}):
        pick_first(records, selected_ids, lambda r, track=track: str(r.get("temporal_track") or "unknown") == track, f"minimum_temporal_track:{track}", reasons)

    for court in sorted({str(r.get("court_level") or "unknown") for r in records}):
        pick_first(records, selected_ids, lambda r, court=court: str(r.get("court_level") or "unknown") == court, f"minimum_court:{court}", reasons)

    special_rules = [
        ("needs_review_automated", lambda r: r.get("status") == "needs_review" or r.get("final_automated_decision") == "needs_review"),
        ("provider_original_unavailable_or_fallback", is_provider_unavailable_or_fallback),
        ("low_yield_partition_output", is_low_yield_partition_record),
        ("current_transition_record", lambda r: r.get("temporal_track") == "current_transition"),
        ("mixed_or_transition_regime", lambda r: r.get("legal_regime") == "mixed_or_transition"),
        ("unknown_regime", lambda r: str(r.get("legal_regime") or "unknown") == "unknown"),
        ("district_or_sessions_record", lambda r: r.get("court_level") == "district_or_sessions"),
    ]
    for reason, predicate in special_rules:
        for _ in range(3 if reason in {"needs_review_automated", "current_transition_record", "mixed_or_transition_regime"} else 1):
            pick_first(records, selected_ids, predicate, reason, reasons)

    family_counts = Counter(str(r.get("offence_family") or "unknown") for r in records)
    family_targets = proportional_targets(family_counts, target)
    by_id = {str(record.get("source_document_id")): record for record in records}
    while len(selected_ids) < min(target, len(records)):
        underfilled = [
            family
            for family, family_target in sorted(family_targets.items())
            if sum(1 for sid in selected_ids if by_id[sid].get("offence_family") == family) < family_target
        ]
        picked = False
        pools = underfilled or sorted(family_counts)
        for family in pools:
            picked = pick_first(
                records,
                selected_ids,
                lambda r, family=family: str(r.get("offence_family") or "unknown") == family,
                f"proportional_fill:{family}",
                reasons,
            )
            if picked:
                break
        if not picked:
            picked = pick_first(records, selected_ids, lambda _r: True, "deterministic_backfill", reasons)
        if not picked:
            break

    selected = [by_id[source_id] for source_id in sorted(selected_ids, key=lambda sid: stable_key(by_id[sid], "final_order"))]
    return selected, reasons


def proportional_targets(counts: Counter[str], target: int) -> dict[str, int]:
    total = sum(counts.values())
    targets: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    for key, count in counts.items():
        raw = target * count / total
        base = min(count, max(1, int(raw)))
        targets[key] = base
        remainders.append((raw - int(raw), key))
    while sum(targets.values()) < target:
        for _remainder, key in sorted(remainders, reverse=True):
            if targets[key] < counts[key] and sum(targets.values()) < target:
                targets[key] += 1
    while sum(targets.values()) > target:
        for _remainder, key in sorted(remainders):
            if targets[key] > 1 and sum(targets.values()) > target:
                targets[key] -= 1
    return targets


def is_provider_unavailable_or_fallback(record: dict[str, Any]) -> bool:
    notes = str(record.get("notes") or "").lower()
    mime = str(record.get("mime_type") or "").lower()
    size = int(record.get("file_size_bytes") or 0)
    return (
        "original" in notes
        or "fallback" in notes
        or (record.get("document_text_available") is True and mime == "application/json" and size < 200)
    )


def is_low_yield_partition_record(record: dict[str, Any]) -> bool:
    return str(record.get("query_id") or "") in {
        "bulk_recent_ipc_hurt_assault",
        "bulk_recent_ipc_criminal_breach_trust",
        "bulk_current_transition_criminal",
        "bulk_landmark_historical_criminal",
    }


def audit_fields() -> dict[str, Any]:
    return {
        "human_audit_status": "pending",
        "criminal_relevance": None,
        "document_type": None,
        "offence_family_review": None,
        "corrected_offence_family": None,
        "legal_regime_review": None,
        "corrected_legal_regime": None,
        "court_metadata_review": None,
        "corrected_court": None,
        "date_metadata_review": None,
        "corrected_date": None,
        "corrected_year": None,
        "text_quality": None,
        "duplicate_or_noise": None,
        "rag_suitability": None,
        "reviewer": None,
        "reviewed_at": None,
        "notes": None,
    }


def sample_record(record: dict[str, Any], index: int, reasons: list[str]) -> dict[str, Any]:
    raw_path = record.get("raw_file_path")
    return {
        "audit_index": index,
        "source_document_id": str(record.get("source_document_id")),
        "canonical_record_id": record.get("local_id"),
        "case_name": record.get("case_name"),
        "offence_family_automated": record.get("offence_family"),
        "legal_regime_automated": record.get("legal_regime") or "unknown",
        "temporal_track": record.get("temporal_track") or "unknown",
        "court_automated": {
            "court_name": record.get("court_name"),
            "court_level": record.get("court_level") or "unknown",
        },
        "judgment_year": record.get("year"),
        "judgment_date": record.get("decision_date"),
        "source_provider": record.get("source_provider"),
        "source_url": record.get("source_url"),
        "sha256": record.get("sha256"),
        "raw_file_path": raw_path,
        "raw_file_exists": bool(raw_path and (REPO_ROOT / str(raw_path)).exists()),
        "mime_type": record.get("mime_type"),
        "file_size_bytes": record.get("file_size_bytes"),
        "document_text_available": bool(record.get("document_text_available")),
        "document_text_quality": record.get("document_text_quality"),
        "document_text_length": record.get("document_text_length"),
        "automated_status": record.get("status"),
        "automated_decision": record.get("final_automated_decision"),
        "quality_scores": record.get("quality_scores") or {},
        "detected_statutes": record.get("detected_statutes") or [],
        "known_sections": record.get("known_sections") or [],
        "regime_evidence": record.get("regime_evidence") or [],
        "acquisition_query": record.get("acquisition_query"),
        "query_id": record.get("query_id"),
        "sample_strata": {
            "offence_family": record.get("offence_family"),
            "legal_regime": record.get("legal_regime") or "unknown",
            "temporal_track": record.get("temporal_track") or "unknown",
            "court_level": record.get("court_level") or "unknown",
            "automated_decision": record.get("final_automated_decision") or record.get("status"),
        },
        "selection_reason": reasons,
        "attribution_required": record.get("attribution_required"),
        "attribution_text": record.get("attribution_text"),
        **audit_fields(),
    }


def generate_sample(
    candidates_path: Path = BULK_CANDIDATES,
    sample_path: Path = SAMPLE_MANIFEST,
    target: int = SAMPLE_SIZE,
) -> list[dict[str, Any]]:
    records = reviewable_records(load_manifest(candidates_path))
    if len(records) != 249:
        raise AuditError(f"expected 249 durable reviewable records, found {len(records)}")
    selected, reasons = allocate_sample(records, target)
    sample = [
        sample_record(record, index, reasons[str(record.get("source_document_id"))])
        for index, record in enumerate(selected, start=1)
    ]
    write_manifest_atomic(sample_path, sample)
    return sample


def preview_for(sample: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    raw_path_value = sample.get("raw_file_path")
    if not raw_path_value:
        return {"available": False, "source": "unavailable", "text": "Preview unavailable: no raw path recorded."}
    raw_path = repo_root / str(raw_path_value)
    if not raw_path.exists():
        return {"available": False, "source": "unavailable", "text": "Preview unavailable: local raw file is missing."}
    mime = str(sample.get("mime_type") or "").lower()
    suffix = raw_path.suffix.lower()
    if mime == "application/pdf" or suffix == ".pdf":
        extraction = extract_pdf_text(raw_path)
        text = extraction.text[:PREVIEW_LIMIT].rstrip()
        return {
            "available": bool(text),
            "source": "pdf_native" if text else "unavailable",
            "text": text or "Preview unavailable: PDF has no native extractable text.",
            "page_count": extraction.page_count,
            "pages_with_text": extraction.pages_with_text,
            "extraction_status": extraction.extraction_status,
            "error": extraction.error,
        }
    if mime.startswith("text/") or suffix in TEXT_SUFFIXES:
        text = clean_text_preview(raw_path.read_text(encoding="utf-8", errors="ignore"), PREVIEW_LIMIT)
        if is_provider_wrapper_text(text) and sample.get("document_text_available"):
            evidence = " ".join(str(item) for item in sample.get("regime_evidence") or [])
            preview = clean_text_preview(evidence, PREVIEW_LIMIT)
            return {
                "available": bool(preview),
                "source": "document_text_fallback_evidence",
                "text": preview or "Preview unavailable: original provider wrapper only; stored full document endpoint text is not in the tracked audit manifest.",
            }
        return {"available": bool(text), "source": "local_text" if text else "unavailable", "text": text or "Preview unavailable: no readable local text found."}
    return {"available": False, "source": "unavailable", "text": "Preview unavailable for this MIME type."}


def is_provider_wrapper_text(text: str) -> bool:
    lowered = text.lower()
    return "original document not available" in lowered or "document not found" in lowered


def preview_stats(samples: list[dict[str, Any]], repo_root: Path = REPO_ROOT) -> dict[str, int]:
    counts = Counter(preview_for(sample, repo_root)["source"] for sample in samples)
    available = sum(count for source, count in counts.items() if source != "unavailable")
    return {
        "sample_records": len(samples),
        "preview_available": available,
        "preview_unavailable": counts.get("unavailable", 0),
        "pdf_based": counts.get("pdf_native", 0),
        "fallback_text_based": counts.get("document_text_fallback_evidence", 0) + counts.get("local_text", 0),
    }


def generate_review_packet(
    sample_path: Path = SAMPLE_MANIFEST,
    output_path: Path = REVIEW_PACKET,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    samples = load_manifest(sample_path)
    lines = [
        "# Bulk Corpus Quality Audit Review Packet",
        "",
        f"Run ID: `{RUN_ID}`",
        f"Sampling version: `{SAMPLING_VERSION}`",
        f"Random seed: `{RANDOM_SEED}`",
        "",
        "All cases remain pending human audit. This packet contains bounded previews only.",
        "",
    ]
    for sample in samples:
        preview = preview_for(sample, repo_root)
        lines.extend(
            [
                f"## Audit {sample['audit_index']:02d}: {field(sample.get('case_name'))}",
                "",
                f"- Source ID: `{field(sample.get('source_document_id'))}`",
                f"- Canonical record ID: `{field(sample.get('canonical_record_id'))}`",
                f"- Court: {field(sample.get('court_automated', {}).get('court_name'))} / `{field(sample.get('court_automated', {}).get('court_level'))}`",
                f"- Date/year: {field(sample.get('judgment_date')) or 'unknown'} / {field(sample.get('judgment_year')) or 'unknown'}",
                f"- Automated offence family: `{field(sample.get('offence_family_automated'))}`",
                f"- Automated legal regime: `{field(sample.get('legal_regime_automated'))}`",
                f"- Temporal track: `{field(sample.get('temporal_track'))}`",
                f"- Automated status/decision: `{field(sample.get('automated_status'))}` / `{field(sample.get('automated_decision'))}`",
                f"- Provenance: `{field(sample.get('source_provider'))}` {field(sample.get('source_url'))}",
                f"- Raw MIME/type: `{field(sample.get('mime_type'))}`",
                f"- Raw path: `{field(sample.get('raw_file_path'))}`",
                f"- Preview source: `{preview['source']}`",
                "",
                "Regime evidence:",
                "",
                bounded_list(sample.get("regime_evidence") or [], limit=3),
                "",
                "Statute references:",
                "",
                bounded_list((sample.get("detected_statutes") or []) + (sample.get("known_sections") or []), limit=8),
                "",
                "Text preview:",
                "",
                "```text",
                str(preview["text"]),
                "```",
                "",
                "Human audit checklist:",
                "",
                "- [ ] criminal_relevance: correct / incorrect / uncertain",
                "- [ ] document_type: judgment / non_judgment / uncertain",
                "- [ ] offence_family_review: confirmed / corrected / uncertain",
                "- [ ] legal_regime_review: confirmed / corrected / uncertain",
                "- [ ] court_metadata_review: correct / corrected / uncertain",
                "- [ ] date_metadata_review: correct / corrected / uncertain",
                "- [ ] text_quality: usable / degraded / unusable",
                "- [ ] duplicate_or_noise: no / duplicate / irrelevant_noise / provider_wrapper_only / other",
                "- [ ] rag_suitability: accept / reject / needs_review",
                "- [ ] reviewer / reviewed_at / bounded notes",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return preview_stats(samples, repo_root)


def bounded_list(values: list[Any], limit: int) -> str:
    if not values:
        return "- none recorded"
    return "\n".join(f"- {clean_text_preview(str(value), 260)}" for value in values[:limit])


def field(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def distribution(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key) or "unknown") for record in records).items()))


def sample_distribution(samples: list[dict[str, Any]], corpus_records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    return {
        "offence_family": paired_distribution(corpus_records, samples, "offence_family", "offence_family_automated"),
        "legal_regime": paired_distribution(corpus_records, samples, "legal_regime", "legal_regime_automated"),
        "temporal_track": paired_distribution(corpus_records, samples, "temporal_track", "temporal_track"),
        "court": paired_distribution(corpus_records, samples, "court_level", ("court_automated", "court_level")),
    }


def paired_distribution(
    corpus: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    corpus_key: str,
    sample_key: str | tuple[str, str],
) -> dict[str, dict[str, int]]:
    corpus_counts = Counter(str(record.get(corpus_key) or "unknown") for record in corpus)
    sample_counts: Counter[str] = Counter()
    for sample in samples:
        if isinstance(sample_key, tuple):
            value = sample.get(sample_key[0], {}).get(sample_key[1])
        else:
            value = sample.get(sample_key)
        sample_counts[str(value or "unknown")] += 1
    keys = sorted(set(corpus_counts) | set(sample_counts))
    return {key: {"corpus_count": corpus_counts.get(key, 0), "sample_count": sample_counts.get(key, 0)} for key in keys}


def completed_reviews(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sample for sample in samples if sample.get("human_audit_status") == "reviewed"]


def ratio(correct: int, total: int) -> dict[str, Any]:
    return {"numerator": correct, "denominator": total, "percent": round(correct * 100 / total, 2) if total else None}


def compute_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = completed_reviews(samples)
    if not reviewed:
        return {
            "reviewed_count": 0,
            "metrics_available": False,
            "criminal_relevance_precision": None,
            "document_type_precision": None,
            "offence_family_accuracy": None,
            "legal_regime_accuracy": None,
            "court_metadata_accuracy": None,
            "date_metadata_accuracy": None,
            "text_usability_rate": None,
            "duplicate_noise_rate": None,
            "rag_suitability_rate": None,
            "human_correction_rate": None,
            "uncertainty_rate": None,
            "stratified": {},
        }
    uncertain = 0
    correction_count = 0
    metrics = {
        "reviewed_count": len(reviewed),
        "metrics_available": True,
        "criminal_relevance_precision": ratio(sum(1 for r in reviewed if r.get("criminal_relevance") == "correct"), sum(1 for r in reviewed if r.get("criminal_relevance") != "uncertain")),
        "document_type_precision": ratio(sum(1 for r in reviewed if r.get("document_type") == "judgment"), sum(1 for r in reviewed if r.get("document_type") != "uncertain")),
        "offence_family_accuracy": ratio(sum(1 for r in reviewed if r.get("offence_family_review") == "confirmed"), sum(1 for r in reviewed if r.get("offence_family_review") != "uncertain")),
        "legal_regime_accuracy": ratio(sum(1 for r in reviewed if r.get("legal_regime_review") == "confirmed"), sum(1 for r in reviewed if r.get("legal_regime_review") != "uncertain")),
        "court_metadata_accuracy": ratio(sum(1 for r in reviewed if r.get("court_metadata_review") == "correct"), sum(1 for r in reviewed if r.get("court_metadata_review") != "uncertain")),
        "date_metadata_accuracy": ratio(sum(1 for r in reviewed if r.get("date_metadata_review") == "correct"), sum(1 for r in reviewed if r.get("date_metadata_review") != "uncertain")),
        "text_usability_rate": ratio(sum(1 for r in reviewed if r.get("text_quality") == "usable"), len(reviewed)),
        "duplicate_noise_rate": ratio(sum(1 for r in reviewed if r.get("duplicate_or_noise") == "no"), len(reviewed)),
        "rag_suitability_rate": ratio(sum(1 for r in reviewed if r.get("rag_suitability") == "accept"), len(reviewed)),
    }
    for record in reviewed:
        for field_name, value in record.items():
            if field_name in REVIEW_ENUMS and value == "uncertain":
                uncertain += 1
        if record.get("offence_family_review") == "corrected" or record.get("legal_regime_review") == "corrected" or record.get("court_metadata_review") == "corrected" or record.get("date_metadata_review") == "corrected":
            correction_count += 1
    metrics["human_correction_rate"] = ratio(correction_count, len(reviewed))
    metrics["uncertainty_rate"] = ratio(uncertain, len(reviewed) * len(REVIEW_ENUMS))
    metrics["stratified"] = stratified_metrics(reviewed)
    return metrics


def stratified_metrics(reviewed: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    strata = {
        "offence_family": lambda r: r.get("offence_family_automated"),
        "legal_regime": lambda r: r.get("legal_regime_automated"),
        "temporal_track": lambda r: r.get("temporal_track"),
        "court_level": lambda r: r.get("court_automated", {}).get("court_level"),
        "query_id": lambda r: r.get("query_id"),
    }
    for name, getter in strata.items():
        bucketed: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in reviewed:
            bucketed[str(getter(record) or "unknown")].append(record)
        output[name] = {
            key: {
                "reviewed": len(items),
                "rag_accept": sum(1 for item in items if item.get("rag_suitability") == "accept"),
                "rag_accept_percent": round(sum(1 for item in items if item.get("rag_suitability") == "accept") * 100 / len(items), 2),
            }
            for key, items in sorted(bucketed.items())
        }
    return output


def correction_matrices(samples: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    reviewed = completed_reviews(samples)
    offence: dict[str, Counter[str]] = defaultdict(Counter)
    regime: dict[str, Counter[str]] = defaultdict(Counter)
    for record in reviewed:
        human_family = record.get("corrected_offence_family") if record.get("offence_family_review") == "corrected" else record.get("offence_family_automated")
        human_regime = record.get("corrected_legal_regime") if record.get("legal_regime_review") == "corrected" else record.get("legal_regime_automated")
        if record.get("offence_family_review") != "uncertain":
            offence[str(record.get("offence_family_automated"))][str(human_family)] += 1
        if record.get("legal_regime_review") != "uncertain":
            regime[str(record.get("legal_regime_automated"))][str(human_regime)] += 1
    return {
        "offence_family": {key: dict(value) for key, value in sorted(offence.items())},
        "legal_regime": {key: dict(value) for key, value in sorted(regime.items())},
    }


def rag_decision_record(sample: dict[str, Any]) -> dict[str, Any]:
    effective_family = (
        sample.get("corrected_offence_family")
        if sample.get("offence_family_review") == "corrected"
        else sample.get("offence_family_automated")
    )
    effective_regime = (
        sample.get("corrected_legal_regime")
        if sample.get("legal_regime_review") == "corrected"
        else sample.get("legal_regime_automated")
    )
    return {
        "source_document_id": sample.get("source_document_id"),
        "human_rag_suitability": sample.get("rag_suitability"),
        "effective_offence_family": effective_family,
        "effective_legal_regime": effective_regime,
        "corrected_date": sample.get("corrected_date"),
        "duplicate_of": sample.get("duplicate_of"),
        "human_review_status": sample.get("human_audit_status"),
    }


def generate_rag_decisions(
    sample_path: Path = SAMPLE_MANIFEST,
    output_path: Path = RAG_DECISIONS_MANIFEST,
) -> list[dict[str, Any]]:
    samples = load_manifest(sample_path)
    decisions = sorted(
        [rag_decision_record(sample) for sample in samples if sample.get("human_audit_status") == "reviewed"],
        key=lambda item: str(item.get("source_document_id")),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(decisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return decisions


def special_case_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "needs_review_ambiguous_automated": sum(1 for s in samples if s.get("automated_status") == "needs_review" or s.get("automated_decision") == "needs_review"),
        "current_transition": sum(1 for s in samples if s.get("temporal_track") == "current_transition"),
        "mixed_or_transition": sum(1 for s in samples if s.get("legal_regime_automated") == "mixed_or_transition"),
        "unknown_regime": sum(1 for s in samples if s.get("legal_regime_automated") == "unknown"),
        "district_or_sessions": sum(1 for s in samples if s.get("court_automated", {}).get("court_level") == "district_or_sessions"),
        "fallback_document_text_records": sum(1 for s in samples if is_provider_unavailable_or_fallback_from_sample(s)),
        "low_yield_partitions": sum(1 for s in samples if is_low_yield_partition_sample(s)),
    }


def is_provider_unavailable_or_fallback_from_sample(sample: dict[str, Any]) -> bool:
    mime = str(sample.get("mime_type") or "").lower()
    size = int(sample.get("file_size_bytes") or 0)
    return bool(sample.get("document_text_available") and mime == "application/json" and size < 200)


def is_low_yield_partition_sample(sample: dict[str, Any]) -> bool:
    return str(sample.get("query_id") or "") in {
        "bulk_recent_ipc_hurt_assault",
        "bulk_recent_ipc_criminal_breach_trust",
        "bulk_current_transition_criminal",
        "bulk_landmark_historical_criminal",
    }


def generate_summary(
    candidates_path: Path = BULK_CANDIDATES,
    sample_path: Path = SAMPLE_MANIFEST,
    summary_path: Path = SUMMARY_MANIFEST,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    corpus = reviewable_records(load_manifest(candidates_path))
    samples = load_manifest(sample_path)
    pending = sum(1 for sample in samples if sample.get("human_audit_status") == "pending")
    rag_decisions = generate_rag_decisions(sample_path)
    summary = {
        "generated_at": utc_now(),
        "run_id": RUN_ID,
        "corpus_size": len(corpus),
        "sample_size": len(samples),
        "sampling_strategy": {
            "version": SAMPLING_VERSION,
            "random_seed": RANDOM_SEED,
            "target_sample_size": SAMPLE_SIZE,
            "algorithm": [
                "filter durable reviewable bulk records only",
                "guarantee one record for each populated offence family",
                "guarantee populated legal-regime, temporal-track, and court-level representation",
                "force bounded special-case coverage",
                "fill remaining slots proportionally by offence-family distribution using stable SHA-256 ordering",
            ],
        },
        "sampling_distribution": sample_distribution(samples, corpus),
        "special_case_counts": special_case_counts(samples),
        "reviewed_count": len(samples) - pending,
        "pending_count": pending,
        "human_audit_state": {
            "pending": pending,
            "reviewed": len(samples) - pending,
            "accepted_for_rag": sum(1 for s in samples if s.get("rag_suitability") == "accept"),
            "rejected_for_rag": sum(1 for s in samples if s.get("rag_suitability") == "reject"),
            "needs_review": sum(1 for s in samples if s.get("rag_suitability") == "needs_review"),
        },
        "metrics": compute_metrics(samples),
        "correction_matrices": correction_matrices(samples),
        "rag_decision_manifest": {
            "path": str(RAG_DECISIONS_MANIFEST.relative_to(REPO_ROOT)),
            "records": len(rag_decisions),
            "accept": sum(1 for item in rag_decisions if item.get("human_rag_suitability") == "accept"),
            "reject": sum(1 for item in rag_decisions if item.get("human_rag_suitability") == "reject"),
            "needs_review": sum(1 for item in rag_decisions if item.get("human_rag_suitability") == "needs_review"),
        },
        "preview_stats": preview_stats(samples, repo_root),
        "no_network_guarantee": {
            "provider_import_required": False,
            "provider_client_constructed": False,
            "llm_dependency": False,
            "embedding_or_rag_work": False,
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def generate_summary_doc(summary_path: Path = SUMMARY_MANIFEST, output_path: Path = SUMMARY_DOC) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    lines = [
        "# Bulk Corpus Quality Audit",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "Status: completed human audit for the 50-record stratified sample.",
        "",
        f"Corpus size: {summary['corpus_size']}",
        f"Sample target: {summary['sampling_strategy']['target_sample_size']}",
        f"Actual sample size: {summary['sample_size']}",
        f"Sampling strategy/version: `{summary['sampling_strategy']['version']}`",
        f"Random seed: `{summary['sampling_strategy']['random_seed']}`",
        "",
        "## RAG Suitability Definition",
        "",
        "A case is suitable for the future global criminal-law RAG corpus when it is a genuinely relevant criminal/legal judgment, has usable text, preserves provenance, is not a semantic or byte duplicate, has enough legal substance for retrieval, and has metadata that is usable or correctable. HTML/text fallback records may be suitable when the stored judgment text is trustworthy.",
        "",
        "## Human Audit Fields",
        "",
        ", ".join(REVIEW_ENUMS.keys()) + ", corrected values, reviewer, reviewed_at, notes.",
        "",
        "## Metric Definitions",
        "",
        "- criminal relevance precision: human relevant / determinate audited records",
        "- document-type precision: judgment / determinate audited records",
        "- offence-family accuracy: confirmed / determinate audited records",
        "- legal-regime accuracy: confirmed / determinate audited records",
        "- court/date metadata accuracy: correct / determinate audited records",
        "- text usability rate: usable / reviewed records",
        "- duplicate/noise rate: no duplicate or noise / reviewed records",
        "- RAG suitability rate: accept / reviewed records",
        "- human correction rate and uncertainty rate",
        "",
        "The remaining 199 bulk records are unaudited/pending. These metrics describe only the reviewed stratified sample unless explicitly labeled as sample-based estimates.",
        "",
        "## Human Decision Totals",
        "",
        f"- reviewed: {summary['reviewed_count']} / {summary['sample_size']}",
        f"- pending sample records: {summary['pending_count']}",
        f"- RAG accept: {summary['human_audit_state']['accepted_for_rag']}",
        f"- RAG reject: {summary['human_audit_state']['rejected_for_rag']}",
        f"- RAG needs_review: {summary['human_audit_state']['needs_review']}",
        "",
        "## Measured Metrics",
        "",
        "| Metric | Numerator | Denominator | Percentage |",
        "| --- | ---: | ---: | ---: |",
        *metric_rows(summary["metrics"]),
        "",
        "## Correction Matrices",
        "",
        "### Offence Family",
        "",
        matrix_table(summary["correction_matrices"]["offence_family"]),
        "",
        "### Legal Regime",
        "",
        matrix_table(summary["correction_matrices"]["legal_regime"]),
        "",
        "## Duplicate And Noise Findings",
        "",
        "- CIC RTI/noise cluster rejected: 27724816, 100481688, 131426670",
        "- Patna duplicate pair: retained 194768350, rejected duplicate 70072092",
        "- Bombay duplicate pair: retained 186425747, rejected duplicate 105760653",
        "- Other non-criminal/noise rejections: 125812430, 120980289",
        "",
        "## Date Metadata Findings",
        "",
        "- Explicit corrected dates were recorded separately from provider date metadata.",
        "- 120980289 has a provider title/date mismatch; human corrected decision date is 2024-03-06.",
        "",
        "## Sample Distribution",
        "",
    ]
    for label, values in summary["sampling_distribution"].items():
        lines.extend([f"### {label}", "", "| Value | Corpus Count | Sample Count |", "| --- | ---: | ---: |"])
        for value, counts in values.items():
            lines.append(f"| {value} | {counts['corpus_count']} | {counts['sample_count']} |")
        lines.append("")
    lines.extend(
        [
            "## Human Review Commands",
            "",
            "Apply one explicit decision:",
            "",
            "```bash",
            "python3 backend/scripts/review_bulk_quality_audit.py apply --source-id SAMPLE_SOURCE_ID --reviewer Ananthu --criminal-relevance correct --document-type judgment --offence-family-review confirmed --legal-regime-review confirmed --court-metadata-review correct --date-metadata-review correct --text-quality usable --duplicate-or-noise no --rag-suitability accept --notes \"bounded human note\"",
            "```",
            "",
            "Regenerate packet and metrics:",
            "",
            "```bash",
            "python3 backend/scripts/review_bulk_quality_audit.py generate",
            "python3 backend/scripts/review_bulk_quality_audit.py summary",
            "```",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def metric_rows(metrics: dict[str, Any]) -> list[str]:
    rows = []
    labels = [
        ("criminal_relevance_precision", "criminal relevance precision"),
        ("document_type_precision", "document type precision"),
        ("offence_family_accuracy", "offence-family accuracy"),
        ("legal_regime_accuracy", "legal-regime accuracy"),
        ("court_metadata_accuracy", "court metadata accuracy"),
        ("date_metadata_accuracy", "date metadata accuracy"),
        ("text_usability_rate", "text usability"),
        ("duplicate_noise_rate", "duplicate/noise clean rate"),
        ("rag_suitability_rate", "RAG suitability rate"),
        ("human_correction_rate", "human correction rate"),
        ("uncertainty_rate", "uncertainty rate"),
    ]
    for key, label in labels:
        value = metrics.get(key) or {}
        percent = value.get("percent")
        rows.append(f"| {label} | {value.get('numerator')} | {value.get('denominator')} | {percent if percent is not None else 'not_available'} |")
    return rows


def matrix_table(matrix: dict[str, dict[str, int]]) -> str:
    if not matrix:
        return "| Automated | Human | Count |\n| --- | --- | ---: |\n| none | none | 0 |"
    lines = ["| Automated | Human | Count |", "| --- | --- | ---: |"]
    for automated, human_counts in matrix.items():
        for human, count in sorted(human_counts.items()):
            lines.append(f"| {automated} | {human} | {count} |")
    return "\n".join(lines)


def apply_review(
    source_id: str,
    reviewer: str,
    sample_path: Path = SAMPLE_MANIFEST,
    **updates: Any,
) -> None:
    samples = load_manifest(sample_path)
    record = next((sample for sample in samples if str(sample.get("source_document_id")) == str(source_id)), None)
    if record is None:
        raise AuditError(f"source_document_id is not in audit sample: {source_id}")
    protected_before = {field_name: record.get(field_name) for field_name in PROTECTED_FIELDS}
    for field_name, allowed in REVIEW_ENUMS.items():
        value = updates.get(field_name)
        if value is not None and value not in allowed:
            raise AuditError(f"invalid {field_name}: {value}")
    corrected_family = updates.get("corrected_offence_family")
    if corrected_family is not None and corrected_family not in OFFENCE_FAMILIES:
        raise AuditError(f"invalid corrected_offence_family: {corrected_family}")
    corrected_regime = updates.get("corrected_legal_regime")
    if corrected_regime is not None and corrected_regime not in LEGAL_REGIMES:
        raise AuditError(f"invalid corrected_legal_regime: {corrected_regime}")
    notes = updates.get("notes")
    if notes is not None and len(str(notes)) > 500:
        raise AuditError("notes must be 500 characters or fewer")

    for key, value in updates.items():
        if value is not None and key in set(REVIEW_ENUMS) | {"corrected_offence_family", "corrected_legal_regime", "corrected_court", "corrected_date", "corrected_year", "notes"}:
            record[key] = value
    record["reviewer"] = reviewer
    record["reviewed_at"] = utc_now()
    record["human_audit_status"] = "reviewed"
    protected_after = {field_name: record.get(field_name) for field_name in PROTECTED_FIELDS}
    if protected_after != protected_before:
        raise AuditError("protected acquisition/provenance fields changed unexpectedly")
    write_manifest_atomic(sample_path, samples)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    generate = subparsers.add_parser("generate", help="Regenerate sample manifest, review packet, and summary.")
    generate.add_argument("--target", type=int, default=SAMPLE_SIZE)
    subparsers.add_parser("summary", help="Regenerate summary JSON and documentation from the current sample.")
    apply = subparsers.add_parser("apply", help="Apply an explicit human audit decision.")
    apply.add_argument("--source-id", required=True)
    apply.add_argument("--reviewer", required=True)
    for field_name, choices in REVIEW_ENUMS.items():
        apply.add_argument(f"--{field_name.replace('_', '-')}", choices=sorted(choices))
    apply.add_argument("--corrected-offence-family", choices=sorted(OFFENCE_FAMILIES))
    apply.add_argument("--corrected-legal-regime", choices=sorted(LEGAL_REGIMES))
    apply.add_argument("--corrected-court")
    apply.add_argument("--corrected-date")
    apply.add_argument("--corrected-year", type=int)
    apply.add_argument("--notes")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {None, "generate"}:
            generate_sample(target=getattr(args, "target", SAMPLE_SIZE))
            generate_review_packet()
            generate_summary()
            generate_summary_doc()
        elif args.command == "summary":
            generate_summary()
            generate_summary_doc()
        elif args.command == "apply":
            updates = {field_name: getattr(args, field_name) for field_name in REVIEW_ENUMS}
            updates.update(
                {
                    "corrected_offence_family": args.corrected_offence_family,
                    "corrected_legal_regime": args.corrected_legal_regime,
                    "corrected_court": args.corrected_court,
                    "corrected_date": args.corrected_date,
                    "corrected_year": args.corrected_year,
                    "notes": args.notes,
                }
            )
            apply_review(args.source_id, args.reviewer, **updates)
            generate_summary()
            generate_summary_doc()
    except AuditError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("Bulk quality audit workflow updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
