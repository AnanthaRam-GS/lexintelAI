"""Deterministic legal query analysis service."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
import re
import unicodedata

from backend.app.schemas.query_analysis import (
    CourtSignal,
    DateSignal,
    ExtractedSignal,
    LegalQueryAnalysis,
    LegalRegimeEvidence,
    SectionSignal,
    StatuteSignal,
    TextSpan,
)
from backend.app.services.legal_regime import resolve_legal_regime


ANALYSIS_VERSION = "legalai-query-analysis-v1"


@dataclass(frozen=True)
class PatternRule:
    canonical: str
    patterns: tuple[str, ...]
    normalized: str | None = None


STATUTE_RULES: tuple[PatternRule, ...] = (
    PatternRule("IPC", (r"\bIPC\b", r"\bIndian Penal Code\b"), "ipc"),
    PatternRule("CrPC", (r"\bCrPC\b", r"\bCr\.?\s*P\.?\s*C\.?\b", r"\bCode of Criminal Procedure\b"), "crpc"),
    PatternRule("BNS", (r"\bBNS\b", r"\bBharatiya Nyaya Sanhita\b"), "bns"),
    PatternRule("BNSS", (r"\bBNSS\b", r"\bBharatiya Nagarik Suraksha Sanhita\b"), "bnss"),
    PatternRule("NDPS Act", (r"\bNDPS(?:\s+Act)?\b", r"\bNarcotic Drugs and Psychotropic Substances Act\b"), "ndps act"),
    PatternRule("POCSO Act", (r"\bPOCSO(?:\s+Act)?\b", r"\bProtection of Children from Sexual Offences Act\b"), "pocso act"),
    PatternRule("SC/ST Act", (r"\bSC/ST(?:\s+Act)?\b", r"\bScheduled Castes and Scheduled Tribes\b.*?\bAct\b"), "sc/st act"),
    PatternRule("Evidence Act", (r"\b(?:Indian\s+)?Evidence Act\b",), "evidence act"),
)

COURT_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("supreme_court", "Supreme Court of India", (r"\bSupreme Court(?: of India)?\b",)),
    ("high_court", "High Court", (r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+)?High Court\b",)),
    ("district_court", "trial court", (r"\btrial court\b",)),
    ("district_court", "Sessions Court", (r"\bSessions Court\b",)),
    ("district_court", "District Court", (r"\bDistrict Court\b",)),
    ("special_court", "Special Court", (r"\bSpecial Court\b",)),
)

POSTURE_RULES: tuple[PatternRule, ...] = (
    PatternRule("anticipatory_bail", (r"\banticipatory bail\b", r"\bpre-arrest bail\b")),
    PatternRule("regular_bail", (r"\bregular bail\b",)),
    PatternRule("default_bail", (r"\bdefault bail\b",)),
    PatternRule("fir_quashing", (r"\bFIR quashing\b", r"\bquashing (?:of )?FIR\b")),
    PatternRule("quashing_petition", (r"\bquashing petition\b",)),
    PatternRule("criminal_appeal", (r"\bcriminal appeal\b", r"\bconviction appeal\b")),
    PatternRule("revision", (r"\brevision\b",)),
    PatternRule("trial", (r"\btrial\b",)),
    PatternRule("investigation", (r"\binvestigation\b",)),
    PatternRule("cognizance", (r"\bcognizance\b",)),
    PatternRule("charge_sheet", (r"\bcharge[- ]sheet\b",)),
    PatternRule("final_report", (r"\bfinal report\b",)),
)

FAMILY_RULES: tuple[PatternRule, ...] = (
    PatternRule("homicide", (r"\bmurder\b", r"\bkilled\b", r"\bdeath caused intentionally\b")),
    PatternRule("hurt_and_assault", (r"\bassault\b", r"\bbeating\b", r"\bgrievous hurt\b")),
    PatternRule("theft", (r"\bstolen property\b", r"\btheft\b", r"\bstealing\b")),
    PatternRule("cheating", (r"\bfalse promise\b", r"\bdishonest inducement\b", r"\bcheating\b")),
    PatternRule("criminal_breach_of_trust", (r"\bentrusted\b", r"\bmisappropriat(?:ed|ion)\b", r"\bcriminal breach of trust\b")),
    PatternRule("kidnapping", (r"\bminor abducted\b", r"\bminor was abducted\b", r"\blured away\b", r"\blured\b", r"\blured away from\b", r"\btaken from guardian\b", r"\blawful custody\b"), "kidnapping"),
    PatternRule("sexual_offences", (r"\brape\b", r"\bsexual assault\b", r"\bsexually assaulted\b", r"\bPOCSO\b")),
    PatternRule("dowry", (r"\bdowry harassment\b", r"\bdowry\b")),
    PatternRule("conspiracy", (r"\bcriminal conspiracy\b", r"\bcommon intention\b", r"\bshared intention\b")),
    PatternRule("narcotics", (r"\bNDPS\b", r"\bnarcotics\b", r"\bdrugs?\b", r"\bganja\b", r"\bheroin\b")),
)

DATE_PATTERNS = (
    re.compile(r"\b(?P<relation>before|after)\s+(?P<day>1|01)[\s./-]*(?P<month>july|07)[\s,./-]*(?P<year>2024)\b", re.IGNORECASE),
    re.compile(r"\b(?P<relation>before|after|post)\s+(?P<month>july)[\s,]*(?P<year>2024)\b", re.IGNORECASE),
    re.compile(r"\b(?P<day>1|01)[./-](?P<month>07)[./-](?P<year>2024)\b", re.IGNORECASE),
    re.compile(r"\b(?P<day>1|01)\s+(?P<month>July)\s+(?P<year>2024)\b", re.IGNORECASE),
    re.compile(r"\b(?P<month>July)\s+(?P<day>1|01),?\s+(?P<year>2024)\b", re.IGNORECASE),
    re.compile(r"\b(?P<year>20\d{2})\b", re.IGNORECASE),
)


def analyze_legal_query(query: str) -> LegalQueryAnalysis:
    original = query
    normalized = normalize_query(query)
    statutes = extract_statutes(original)
    sections = extract_sections(original, statutes)
    dates = extract_dates(original)
    courts = extract_courts(original)
    posture = extract_rule_signals(original, POSTURE_RULES)
    families = extract_rule_signals(original, FAMILY_RULES, source="deterministic_inference")
    legal_terms = stable_signals([*posture, *families])
    resolved = resolve_legal_regime(original)
    warnings = build_warnings(statutes, sections, dates, families, resolved.regime)
    analysis = LegalQueryAnalysis(
        original_query=original,
        normalized_query=normalized,
        explicit_statutes=statutes,
        explicit_sections=sections,
        explicit_legal_terms=legal_terms,
        dates=dates,
        date_ranges=[date for date in dates if date.relation == "range"],
        court_mentions=courts,
        procedural_posture=posture,
        offence_family_hints=families,
        legal_regime=resolved.regime,
        legal_regime_confidence=resolved.confidence,
        legal_regime_evidence=LegalRegimeEvidence(
            explicit_codes=resolved.explicit_codes,
            explicit_sections=resolved.explicit_sections,
            detected_dates=resolved.detected_dates,
            transition_terms=resolved.transition_terms,
        ),
        entities=[],
        predicted_sections=[],
        warnings=warnings,
        analysis_version=ANALYSIS_VERSION,
    )
    from backend.app.services.legal_section_prediction import predict_legal_sections_from_analysis

    predicted = predict_legal_sections_from_analysis(analysis)
    return analysis.model_copy(update={"predicted_sections": predicted})


def normalize_query(query: str) -> str:
    text = unicodedata.normalize("NFKC", query).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(?:Sec|S)\.?\s*(?=\d)", "Section ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSections?\s+", lambda m: "Sections " if m.group(0).lower().startswith("sections") else "Section ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,?.])", r"\1", text)
    return text


def extract_statutes(query: str) -> list[StatuteSignal]:
    found: OrderedDict[str, StatuteSignal] = OrderedDict()
    for rule in STATUTE_RULES:
        for pattern in rule.patterns:
            for match in re.finditer(pattern, query, flags=re.IGNORECASE):
                found.setdefault(
                    f"{rule.canonical}:{match.start()}",
                    StatuteSignal(
                        value=match.group(0),
                        normalized=rule.normalized or rule.canonical.casefold(),
                        canonical=rule.canonical,
                        source="explicit",
                        span=span(match),
                    ),
                )
    return sorted(found.values(), key=lambda item: (item.span.start if item.span else 0, item.canonical))


def extract_sections(query: str, statutes: list[StatuteSignal]) -> list[SectionSignal]:
    normalized_query = normalize_query(query)
    section_blocks = re.finditer(r"\bSections?\s+([0-9A-Za-z(),\s.-]+?)(?=\s+(?:IPC|CrPC|BNS|BNSS|NDPS|POCSO|SC/ST|Indian Penal Code|Code of Criminal Procedure|Bharatiya|Act)\b|[?.;]|$)", normalized_query, flags=re.IGNORECASE)
    signals: list[SectionSignal] = []
    for block in section_blocks:
        block_text = block.group(0)
        statute = nearest_following_statute(normalized_query, block.end())
        numbers = re.findall(r"\d+[A-Za-z]?(?:\(\d+[A-Za-z]?\))?", block.group(1))
        for number in numbers:
            start = normalized_query.find(number, block.start())
            signals.append(
                SectionSignal(
                    value=number,
                    normalized=number.casefold(),
                    section=number,
                    statute=statute,
                    source="explicit",
                    span=TextSpan(start=start, end=start + len(number), text=number),
                )
            )
    return signals


def nearest_following_statute(text: str, index: int) -> str | None:
    window = text[index : index + 80]
    statutes = extract_statutes(window)
    return statutes[0].canonical if statutes else None


def extract_dates(query: str) -> list[DateSignal]:
    output: list[DateSignal] = []
    seen: set[tuple[int, int]] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(query):
            if (match.start(), match.end()) in seen:
                continue
            seen.add((match.start(), match.end()))
            relation = match.groupdict().get("relation") or "on"
            relation = "after" if relation == "post" else relation
            norm = normalize_date_parts(match.groupdict())
            output.append(DateSignal(value=match.group(0), normalized=match.group(0).casefold(), source="explicit", span=span(match), relation=relation if relation in {"before", "after", "on"} else "unknown", normalized_date=norm))
    if re.search(r"after commencement of new criminal laws", query, flags=re.IGNORECASE):
        output.append(DateSignal(value="after commencement of new criminal laws", normalized="after commencement of new criminal laws", source="explicit", relation="after", normalized_date="2024-07-01"))
    return sorted(output, key=lambda item: item.span.start if item.span else 10**9)


def normalize_date_parts(parts: dict[str, str | None]) -> str | None:
    year = parts.get("year")
    if not year:
        return None
    if not parts.get("day") and not parts.get("month"):
        return year
    month = 7 if str(parts.get("month")).casefold() in {"july", "07"} else None
    day = int(parts.get("day") or 1)
    if month:
        return date(int(year), month, day).isoformat()
    return year


def extract_courts(query: str) -> list[CourtSignal]:
    output: list[CourtSignal] = []
    for level, name, patterns in COURT_RULES:
        for pattern in patterns:
            for match in re.finditer(pattern, query, flags=re.IGNORECASE):
                output.append(CourtSignal(value=match.group(0), normalized=match.group(0).casefold(), source="explicit", span=span(match), court_level=level, court_name=name if name != "High Court" else match.group(0)))
    return sorted(output, key=lambda item: item.span.start if item.span else 0)


def extract_rule_signals(query: str, rules: tuple[PatternRule, ...], source: str = "explicit") -> list[ExtractedSignal]:
    output: OrderedDict[str, ExtractedSignal] = OrderedDict()
    for rule in rules:
        for pattern in rule.patterns:
            for match in re.finditer(pattern, query, flags=re.IGNORECASE):
                output.setdefault(
                    rule.canonical,
                    ExtractedSignal(value=match.group(0), normalized=rule.normalized or rule.canonical, source=source, span=span(match), confidence="high"),
                )
    return list(output.values())


def stable_signals(signals: list[ExtractedSignal]) -> list[ExtractedSignal]:
    dedup: OrderedDict[str, ExtractedSignal] = OrderedDict()
    for signal in signals:
        dedup.setdefault(f"{signal.source}:{signal.normalized}", signal)
    return list(dedup.values())


def build_warnings(statutes: list[StatuteSignal], sections: list[SectionSignal], dates: list[DateSignal], families: list[ExtractedSignal], regime: str) -> list[str]:
    warnings: list[str] = []
    if any(section.statute is None for section in sections):
        warnings.append("section_without_explicit_statute")
    canon = {statute.canonical for statute in statutes}
    if canon & {"IPC", "CrPC"} and canon & {"BNS", "BNSS"}:
        warnings.append("conflicting_old_new_statutes")
    if dates and regime == "unknown":
        warnings.append("ambiguous_date_context")
    if len(families) > 1:
        warnings.append("multiple_offence_families")
    return warnings


def span(match: re.Match[str]) -> TextSpan:
    return TextSpan(start=match.start(), end=match.end(), text=match.group(0))
