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
    change_type: str


class NcrbStatPoint(BaseModel):
    """NCRB statistics row."""

    year: int
    state: str
    offense_category: str
    ipc_section: str | None = None
    case_count: int
    conviction_count: int | None = None
    acquittal_count: int | None = None
