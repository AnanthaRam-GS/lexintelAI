"""Analytics API endpoints for LegalAI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.analytics import (
    IpcBnsMappingRow,
    NcrbStatPoint,
    OffenseFrequencyPoint,
    OutcomeDistributionPoint,
    SectionCooccurrencePoint,
)
from backend.app.services.analytics import (
    AnalyticsFilterError,
    get_ipc_bns_mappings,
    get_ncrb_stats,
    get_offence_frequency,
    get_outcome_distribution,
    get_section_cooccurrence,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _handle_filter_error(exc: AnalyticsFilterError) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/offence-frequency", response_model=list[OffenseFrequencyPoint], operation_id="get_offence_frequency")
@router.get("/offense-frequency", response_model=list[OffenseFrequencyPoint], operation_id="get_offense_frequency_contract")
def offence_frequency(
    year: int | None = Query(None),
    section: str | None = Query(None),
    include_all_sections: bool = Query(False, description="Also count procedural, definitional and liability-linking provisions."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[OffenseFrequencyPoint]:
    """Return offence frequency counts by statutory section and year (offence provisions only by default)."""
    try:
        return get_offence_frequency(db, year=year, section=section, include_all_sections=include_all_sections)
    except AnalyticsFilterError as exc:
        _handle_filter_error(exc)


@router.get("/outcome-distribution", response_model=list[OutcomeDistributionPoint])
def outcome_distribution(
    section: str | None = Query(None),
    court_level: str | None = Query(None),
    include_all_sections: bool = Query(False, description="Also include non-offence provisions."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[OutcomeDistributionPoint]:
    """Return normalized conviction and appeal outcome counts (offence provisions only by default)."""
    try:
        return get_outcome_distribution(
            db, section=section, court_level=court_level, include_all_sections=include_all_sections
        )
    except AnalyticsFilterError as exc:
        _handle_filter_error(exc)


@router.get("/section-cooccurrence", response_model=list[SectionCooccurrencePoint])
def section_cooccurrence(
    section: str | None = Query(None),
    include_all_sections: bool = Query(False, description="Also include non-offence provisions."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[SectionCooccurrencePoint]:
    """Return co-occurrence counts for pairs of statutory sections (offence provisions only by default)."""
    try:
        return get_section_cooccurrence(db, section=section, include_all_sections=include_all_sections)
    except AnalyticsFilterError as exc:
        _handle_filter_error(exc)


@router.get("/ipc-bns", response_model=list[IpcBnsMappingRow], operation_id="get_ipc_bns_mapping")
@router.get("/ipc-bns-map", response_model=list[IpcBnsMappingRow], operation_id="get_ipc_bns_map_contract")
def ipc_bns_mapping(
    ipc_section: str | None = Query(None),
    bns_section: str | None = Query(None),
    change_type: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[IpcBnsMappingRow]:
    """Return IPC to BNS mapping rows."""
    try:
        return get_ipc_bns_mappings(
            db,
            ipc_section=ipc_section,
            bns_section=bns_section,
            change_type=change_type,
        )
    except AnalyticsFilterError as exc:
        _handle_filter_error(exc)


@router.get("/ncrb", response_model=list[NcrbStatPoint], operation_id="get_ncrb_stats")
@router.get("/ncrb-stats", response_model=list[NcrbStatPoint], operation_id="get_ncrb_stats_contract")
def ncrb_filtering(
    year: int | None = Query(None),
    state: str | None = Query(None),
    offense_category: str | None = Query(None),
    ipc_section: str | None = Query(None),
    include_aggregates: bool = Query(False, description="Also return state/UT/all-India totals and subtotal heads."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[NcrbStatPoint]:
    """Return NCRB statistics filtered by year, state, category, or section (aggregate rows excluded by default)."""
    try:
        return get_ncrb_stats(
            db,
            year=year,
            state=state,
            offense_category=offense_category,
            ipc_section=ipc_section,
            include_aggregates=include_aggregates,
        )
    except AnalyticsFilterError as exc:
        _handle_filter_error(exc)
