"""Deterministic, bounded legal query expansion."""

from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import mean, median
from typing import Any


MAX_EXPANSION_TERMS = 10


@dataclass(frozen=True)
class ExpansionGroup:
    group_type: str
    trigger: str
    terms: tuple[str, ...]
    confidence: str
    evidence: str
    discriminator: bool = False


@dataclass(frozen=True)
class LegalQueryExpansion:
    original_query: str
    expanded_terms: list[str]
    expansion_groups: list[ExpansionGroup]
    confidence: str
    evidence: list[str]
    warnings: list[str]


STATUTE_ALIASES: tuple[ExpansionGroup, ...] = (
    ExpansionGroup("statute_alias", "ipc", ("Indian Penal Code",), "high", "explicit IPC alias"),
    ExpansionGroup("statute_alias", "indian penal code", ("IPC",), "high", "explicit Indian Penal Code alias"),
    ExpansionGroup("statute_alias", "crpc", ("Code of Criminal Procedure",), "high", "explicit CrPC alias"),
    ExpansionGroup("statute_alias", "code of criminal procedure", ("CrPC",), "high", "explicit Code of Criminal Procedure alias"),
    ExpansionGroup("statute_alias", "bns", ("Bharatiya Nyaya Sanhita",), "high", "explicit BNS alias"),
    ExpansionGroup("statute_alias", "bharatiya nyaya sanhita", ("BNS",), "high", "explicit Bharatiya Nyaya Sanhita alias"),
    ExpansionGroup("statute_alias", "bnss", ("Bharatiya Nagarik Suraksha Sanhita",), "high", "explicit BNSS alias"),
    ExpansionGroup("statute_alias", "bharatiya nagarik suraksha sanhita", ("BNSS",), "high", "explicit Bharatiya Nagarik Suraksha Sanhita alias"),
)


LEXICON: tuple[ExpansionGroup, ...] = (
    ExpansionGroup("procedure_equivalent", "anticipatory bail", ("pre-arrest bail",), "high", "procedural equivalent", True),
    ExpansionGroup("procedure_equivalent", "regular bail", ("bail after arrest",), "high", "procedural equivalent", True),
    ExpansionGroup("procedure_equivalent", "fir quashing", ("quashing of FIR", "criminal petition"), "high", "procedural equivalent"),
    ExpansionGroup("procedure_equivalent", "arrest safeguards", ("notice of appearance", "arrest procedure"), "high", "procedural safeguard terminology", True),
    ExpansionGroup("transition_term", "new procedural code", ("BNSS", "Bharatiya Nagarik Suraksha Sanhita"), "medium", "generic new procedure reference"),
    ExpansionGroup("transition_term", "old crpc", ("Code of Criminal Procedure",), "high", "explicit old procedure reference"),
    ExpansionGroup("transition_term", "before july 2024", ("old criminal law", "commencement", "savings clause"), "medium", "transition timing"),
    ExpansionGroup("transition_term", "after commencement", ("new criminal law", "commencement"), "medium", "transition timing"),
    ExpansionGroup("plain_language_legal_mapping", "entrusted money", ("criminal breach of trust", "entrustment", "misappropriation"), "high", "entrustment terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "entrusted", ("criminal breach of trust", "entrustment", "misappropriation"), "high", "entrustment terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "dishonestly retained", ("criminal breach of trust", "entrustment", "misappropriation"), "high", "entrustment terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "false promise", ("cheating", "dishonest inducement", "fraudulent intention"), "high", "cheating requires inducement language", True),
    ExpansionGroup("plain_language_legal_mapping", "induced to part with money", ("cheating", "dishonest inducement", "fraudulent intention"), "high", "cheating inducement language", True),
    ExpansionGroup("plain_language_legal_mapping", "property taken by force", ("robbery", "theft", "hurt", "fear", "wrongful restraint"), "high", "robbery-force distinction", True),
    ExpansionGroup("plain_language_legal_mapping", "taken after threatening", ("robbery", "theft", "hurt", "fear", "wrongful restraint"), "high", "robbery threat distinction", True),
    ExpansionGroup("plain_language_legal_mapping", "shared intention", ("common intention",), "high", "common-intention terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "group assault", ("common intention", "assault"), "medium", "group-assault concept"),
    ExpansionGroup("plain_language_legal_mapping", "lawful custody", ("kidnapping", "lawful guardianship", "taking", "enticing"), "high", "kidnapping guardianship terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "lured away", ("kidnapping", "lawful guardianship", "taking", "enticing"), "high", "kidnapping guardianship terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "marriage demands", ("dowry demand", "cruelty by husband or relatives"), "high", "dowry cruelty terminology", True),
    ExpansionGroup("plain_language_legal_mapping", "husband and in laws", ("cruelty by husband or relatives",), "medium", "domestic cruelty terminology"),
    ExpansionGroup("hard_negative_disambiguation", "breach of contract wrongly framed as cheating", ("dishonest intention at inception", "contractual breach", "civil dispute"), "high", "cheating/civil dispute discriminator", True),
    ExpansionGroup("hard_negative_disambiguation", "wrongly framed as cheating", ("dishonest intention at inception", "contractual breach", "civil dispute"), "high", "cheating/civil dispute discriminator", True),
    ExpansionGroup("offence_equivalent", "culpable homicide", ("not amounting to murder",), "high", "homicide distinction", True),
)


SECTION_PATTERN = re.compile(r"\bsection\s+\d+[a-z]?\b", re.IGNORECASE)


def expand_legal_query(query: str, max_terms: int = MAX_EXPANSION_TERMS) -> LegalQueryExpansion:
    normalized = " ".join(query.casefold().split())
    groups: list[ExpansionGroup] = []
    warnings: list[str] = []
    for group in (*STATUTE_ALIASES, *LEXICON):
        if group.trigger in normalized:
            groups.append(group)
    if "breach of contract" in normalized and not any(term in normalized for term in ["cheating", "dishonest", "fraudulent", "induced", "inducement", "wrongly framed"]):
        warnings.append("breach_of_contract_not_expanded_to_cheating_without_fraud_language")
        groups = [group for group in groups if "cheating" not in group.terms]
    if SECTION_PATTERN.search(query):
        warnings.append("explicit_section_retained_without_cross_statute_mapping")
    terms: list[str] = []
    seen = {normalized}
    for group in groups:
        for term in group.terms:
            key = term.casefold()
            if key not in seen and len(terms) < max_terms:
                terms.append(term)
                seen.add(key)
    if sum(len(group.terms) for group in groups) > len(terms):
        warnings.append("expansion_budget_truncated")
    confidence = "high" if any(group.confidence == "high" for group in groups) else "medium" if groups else "low"
    return LegalQueryExpansion(
        original_query=query,
        expanded_terms=terms,
        expansion_groups=groups,
        confidence=confidence,
        evidence=[group.evidence for group in groups],
        warnings=warnings,
    )


def expanded_query_text(query: str, variant: str) -> str:
    expansion = expand_legal_query(query)
    if variant == "Q0" or not expansion.expanded_terms:
        return query
    high_terms = terms_for_variant(expansion, variant)
    if variant == "Q1":
        return f"{query} | {' '.join(high_terms)}" if high_terms else query
    if variant == "Q2":
        return f"{query} {query} | {' '.join(high_terms)}" if high_terms else query
    if variant == "Q3":
        discriminators = [term for group in expansion.expansion_groups if group.discriminator for term in group.terms if term in expansion.expanded_terms]
        selected = stable_unique([*high_terms, *discriminators])[:MAX_EXPANSION_TERMS]
        return f"{query} {query} | {' '.join(selected)}" if selected else query
    raise ValueError(f"unknown query expansion variant: {variant}")


def terms_for_variant(expansion: LegalQueryExpansion, variant: str) -> list[str]:
    if variant == "Q1":
        return [term for group in expansion.expansion_groups if group.confidence == "high" for term in group.terms if term in expansion.expanded_terms]
    if variant in {"Q2", "Q3"}:
        return list(expansion.expanded_terms)
    return []


def stable_unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            output.append(value)
            seen.add(key)
    return output


def expansion_summary(expansions: list[LegalQueryExpansion]) -> dict[str, Any]:
    counts = [len(expansion.expanded_terms) for expansion in expansions]
    return {
        "queries_expanded": sum(1 for count in counts if count),
        "mean_terms": round(mean(counts), 6) if counts else 0.0,
        "median_terms": round(median(counts), 6) if counts else 0.0,
        "max_terms": max(counts) if counts else 0,
        "warning_count": sum(len(expansion.warnings) for expansion in expansions),
    }
