"""Analytics API response contracts for LegalAI dashboards."""

from pydantic import BaseModel


class OffenseFrequencyPoint(BaseModel):
    """Offense frequency count for a section and year."""

    section: str
    year: int
    count: int


class OutcomeDistributionPoint(BaseModel):
    """Case outcome distribution by section and court level."""

    section: str
    court_level: str
    convicted: int
    acquitted: int
    appeal_allowed: int
    appeal_dismissed: int


class SectionCooccurrencePoint(BaseModel):
    """Co-occurrence count for two statutory sections."""

    section_a: str
    section_b: str
    count: int


class IpcBnsMappingRow(BaseModel):
    """IPC to BNS mapping row."""

    ipc_section: str
    ipc_description: str
    bns_section: str | None = None
    bns_description: str | None = None
    # None for a row whose source gives no change type (an NCRB-printed pair); never guessed (step 19b).
    change_type: str | None = None
    # CYTRAIN or NCRB_CII_2024_T1A4; source_page is the printed table page of an NCRB row.
    source: str
    source_page: int | None = None
    # Step 26b: the official India Code heading of the IPC / BNS section (the parent section's for a sub-section),
    # when one exists; the source descriptions above are kept as they are.
    ipc_official_heading: str | None = None
    bns_official_heading: str | None = None
    # True when the row's description is listed in data/structured/statute_headings/mapping_conflicts.csv: it differs
    # in meaning from the official heading (e.g. IPC 376 rows carrying the headings of sections 376A-376E).
    ipc_description_conflicts_with_official: bool = False
    bns_description_conflicts_with_official: bool = False


class NcrbStatPoint(BaseModel):
    """NCRB statistics row."""

    year: int
    state: str
    offense_category: str
    ipc_section: str | None = None
    bns_section: str | None = None
    case_count: int | None = None
    conviction_count: int | None = None
    acquittal_count: int | None = None
    is_aggregate: bool = False
    aggregate_type: str | None = None
    # Step 15b: statute-qualified labels parsed from the printed section text ("IPC 305"), used by the
    # section filter, and a UI label that differs from the printed head only for an evident printing error.
    ipc_section_labels: list[str] | None = None
    bns_section_labels: list[str] | None = None
    display_offense_category: str | None = None
