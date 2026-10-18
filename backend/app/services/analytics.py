"""Analytics query services for LegalAI dashboards.

Computes offence frequency, normalized outcome distribution, and section
co-occurrence from the judgment corpus, and filters IPC-BNS and NCRB rows
from structured reference tables.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.models import Document, DocumentSection, IpcBnsMapping, NcrbStat
from backend.app.models.analytics import (
    IpcBnsMappingRow,
    NcrbStatPoint,
    OffenseFrequencyPoint,
    OutcomeDistributionPoint,
    SectionCooccurrencePoint,
)

ALLOWED_CHANGE_TYPES = {
    "DIRECT",
    "SPLIT",
    "MERGED",
    "REPEALED",
    "NO_DIRECT_EQUIVALENT",
}

CONVICTED_LABELS = {
    "convicted",
    "conviction",
    "guilty",
    "found guilty",
}
ACQUITTED_LABELS = {
    "acquitted",
    "acquittal",
    "not guilty",
    "discharged",
}
APPEAL_ALLOWED_LABELS = {
    "allowed",
    "appeal allowed",
    "allowed in part",
    "partly allowed",
    "partially allowed",
    "reversed",
}
APPEAL_DISMISSED_LABELS = {
    "dismissed",
    "appeal dismissed",
    "rejected",
    "refused",
    "upheld",
}


class AnalyticsFilterError(ValueError):
    """Raised when an analytics filter value is invalid."""


def _normalize_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _optional_filter_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        raise AnalyticsFilterError(f"Invalid {field_name}: value must not be empty.")
    return cleaned


def _optional_year(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1900 or value > 2100:
        raise AnalyticsFilterError("Invalid year: must be between 1900 and 2100.")
    return value


def section_label(statute: str | None, section: str) -> str:
    """Statute-qualified section label, e.g. "IPC 302" (the frontend contract).

    Grouping by the bare number would merge different provisions that share
    a number, such as IPC 302 and BNS 302.
    """
    return f"{statute} {section}" if statute else section


def _section_filter(query, section: str | None):
    """Filter by a full label ("IPC 302") or by a bare section number across statutes."""
    if section is None:
        return query
    label = func.concat(DocumentSection.statute, " ", DocumentSection.section)
    return query.filter((label == section) | (DocumentSection.section == section))


def _conviction_bucket(value: str | None) -> str | None:
    label = _normalize_label(value)
    if label in CONVICTED_LABELS:
        return "convicted"
    if label in ACQUITTED_LABELS:
        return "acquitted"
    return None


def _appeal_bucket(value: str | None) -> str | None:
    label = _normalize_label(value)
    if label in APPEAL_ALLOWED_LABELS:
        return "appeal_allowed"
    if label in APPEAL_DISMISSED_LABELS:
        return "appeal_dismissed"
    return None


def get_offence_frequency(
    db: Session,
    *,
    year: int | None = None,
    section: str | None = None,
) -> list[OffenseFrequencyPoint]:
    """Count distinct corpus documents per statutory section and year."""
    year = _optional_year(year)
    section = _optional_filter_text(section, "section")

    query = (
        db.query(
            DocumentSection.statute,
            DocumentSection.section,
            Document.year,
            func.count(func.distinct(Document.id)),
        )
        .join(Document, Document.id == DocumentSection.document_id)
        .filter(Document.year.isnot(None))
        .filter(DocumentSection.section.isnot(None))
        .filter(DocumentSection.section != "")
    )
    if year is not None:
        query = query.filter(Document.year == year)
    query = _section_filter(query, section)

    rows = (
        query.group_by(DocumentSection.statute, DocumentSection.section, Document.year)
        .order_by(
            Document.year.desc(),
            func.count(func.distinct(Document.id)).desc(),
            DocumentSection.statute,
            DocumentSection.section,
        )
        .all()
    )
    return [
        OffenseFrequencyPoint(section=section_label(row[0], row[1]), year=int(row[2]), count=int(row[3]))
        for row in rows
    ]


def get_outcome_distribution(
    db: Session,
    *,
    section: str | None = None,
    court_level: str | None = None,
) -> list[OutcomeDistributionPoint]:
    """Return outcome counts with labels normalized into canonical buckets."""
    section = _optional_filter_text(section, "section")
    court_level = _optional_filter_text(court_level, "court_level")

    query = (
        db.query(Document, DocumentSection.statute, DocumentSection.section)
        .join(DocumentSection, DocumentSection.document_id == Document.id)
        .filter(Document.court_level.isnot(None))
        .filter(Document.court_level != "")
        .filter(DocumentSection.section.isnot(None))
        .filter(DocumentSection.section != "")
    )
    query = _section_filter(query, section)
    if court_level is not None:
        query = query.filter(Document.court_level == court_level)

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {
            "convicted": 0,
            "acquitted": 0,
            "appeal_allowed": 0,
            "appeal_dismissed": 0,
        }
    )
    seen_conviction: dict[tuple[str, str, int, str], None] = {}
    seen_appeal: dict[tuple[str, str, int, str], None] = {}

    for document, statute, raw_section in query.all():
        section_value = section_label(statute, raw_section)
        key = (section_value, document.court_level)
        grouped[key]  # ensure the pair is present even if outcomes are unknown

        conviction = _conviction_bucket(document.conviction_status)
        if conviction is None:
            conviction = _conviction_bucket(document.case_disposition)
        if conviction is not None:
            identity = (section_value, document.court_level, document.id, conviction)
            if identity not in seen_conviction:
                grouped[key][conviction] += 1
                seen_conviction[identity] = None

        appeal = _appeal_bucket(document.appeal_result)
        if appeal is not None:
            identity = (section_value, document.court_level, document.id, appeal)
            if identity not in seen_appeal:
                grouped[key][appeal] += 1
                seen_appeal[identity] = None

    return [
        OutcomeDistributionPoint(
            section=section_value,
            court_level=level,
            convicted=counts["convicted"],
            acquitted=counts["acquitted"],
            appeal_allowed=counts["appeal_allowed"],
            appeal_dismissed=counts["appeal_dismissed"],
        )
        for (section_value, level), counts in sorted(grouped.items())
    ]


def get_section_cooccurrence(
    db: Session,
    *,
    section: str | None = None,
) -> list[SectionCooccurrencePoint]:
    """Count distinct documents in which two statutory sections co-occur."""
    section = _optional_filter_text(section, "section")

    rows = (
        db.query(DocumentSection.document_id, DocumentSection.statute, DocumentSection.section)
        .filter(DocumentSection.section.isnot(None))
        .filter(DocumentSection.section != "")
        .all()
    )
    sections_by_document: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for document_id, statute, section_value in rows:
        sections_by_document[document_id].add((section_label(statute, section_value), section_value))

    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for section_set in sections_by_document.values():
        unique_sections = sorted(section_set)
        for (label_a, bare_a), (label_b, bare_b) in combinations(unique_sections, 2):
            if section is not None and section not in {label_a, label_b, bare_a, bare_b}:
                continue
            pair_counts[(label_a, label_b)] += 1

    return [
        SectionCooccurrencePoint(section_a=pair[0], section_b=pair[1], count=count)
        for pair, count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]


def get_ipc_bns_mappings(
    db: Session,
    *,
    ipc_section: str | None = None,
    bns_section: str | None = None,
    change_type: str | None = None,
) -> list[IpcBnsMappingRow]:
    """Return IPC-BNS mapping rows, optionally filtered."""
    ipc_section = _optional_filter_text(ipc_section, "ipc_section")
    bns_section = _optional_filter_text(bns_section, "bns_section")
    change_type = _optional_filter_text(change_type, "change_type")
    if change_type is not None:
        change_type = change_type.upper()
        if change_type not in ALLOWED_CHANGE_TYPES:
            allowed = ", ".join(sorted(ALLOWED_CHANGE_TYPES))
            raise AnalyticsFilterError(
                f"Invalid change_type: must be one of {allowed}."
            )

    query = db.query(IpcBnsMapping)
    if ipc_section is not None:
        query = query.filter(IpcBnsMapping.ipc_section == ipc_section)
    if bns_section is not None:
        query = query.filter(IpcBnsMapping.bns_section == bns_section)
    if change_type is not None:
        query = query.filter(IpcBnsMapping.change_type == change_type)

    rows = query.order_by(IpcBnsMapping.ipc_section, IpcBnsMapping.bns_section, IpcBnsMapping.id).all()
    return [
        IpcBnsMappingRow(
            ipc_section=row.ipc_section,
            ipc_description=row.ipc_description,
            bns_section=row.bns_section,
            bns_description=row.bns_description,
            change_type=row.change_type,
        )
        for row in rows
    ]


def get_ncrb_stats(
    db: Session,
    *,
    year: int | None = None,
    state: str | None = None,
    offense_category: str | None = None,
    ipc_section: str | None = None,
) -> list[NcrbStatPoint]:
    """Return NCRB statistics rows matching the supplied filters."""
    year = _optional_year(year)
    state = _optional_filter_text(state, "state")
    offense_category = _optional_filter_text(offense_category, "offense_category")
    ipc_section = _optional_filter_text(ipc_section, "ipc_section")

    query = db.query(NcrbStat)
    if year is not None:
        query = query.filter(NcrbStat.year == year)
    if state is not None:
        query = query.filter(func.lower(NcrbStat.state) == state.lower())
    if offense_category is not None:
        query = query.filter(func.lower(NcrbStat.offense_category) == offense_category.lower())
    if ipc_section is not None:
        query = query.filter(NcrbStat.ipc_section == ipc_section)

    rows = query.order_by(
        NcrbStat.year.desc(),
        NcrbStat.state,
        NcrbStat.offense_category,
        NcrbStat.id,
    ).all()
    return [
        NcrbStatPoint(
            year=row.year,
            state=row.state,
            offense_category=row.offense_category,
            ipc_section=row.ipc_section,
            case_count=row.case_count,
            conviction_count=row.conviction_count,
            acquittal_count=row.acquittal_count,
        )
        for row in rows
    ]
