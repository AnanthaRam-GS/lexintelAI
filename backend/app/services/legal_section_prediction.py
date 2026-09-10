"""Deterministic supplementary legal section prediction foundation."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any

from backend.app.schemas.query_analysis import LegalQueryAnalysis, PredictedLegalSection
from backend.app.services.legal_regime import resolve_legal_regime


REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"
PREDICTION_VERSION = "legalai-section-prediction-baseline-v1"
DEFAULT_TOP_K = 5

REGIME_STATUTES = {
    "ipc_crpc": {"IPC", "CrPC", "NDPS Act", "POCSO Act", "SC/ST Act"},
    "bns_bnss": {"BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act"},
    "mixed_or_transition": {"IPC", "CrPC", "BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act"},
    "unknown": {"IPC", "CrPC", "BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act"},
}

CONCEPT_PATTERNS: dict[str, tuple[str, ...]] = {
    "homicide": (r"\bmurder\b", r"\bkilled\b", r"\bculpable homicide\b"),
    "attempt_to_murder": (r"\battempt(?:ed)? murder\b", r"\battempt to murder\b"),
    "hurt_and_assault": (r"\bassault\b", r"\bbeating\b", r"\bgrievous hurt\b", r"\bhurt\b"),
    "theft": (r"\btheft\b", r"\bstolen\b", r"\bstealing\b"),
    "robbery": (r"\brobbery\b", r"\bsnatching\b", r"\brobbed\b"),
    "cheating": (r"\bcheating\b", r"\bfalse promise\b", r"\bdishonest inducement\b"),
    "criminal_breach_of_trust": (r"\bcriminal breach of trust\b", r"\bentrusted\b", r"\bmisappropriat"),
    "kidnapping": (r"\bkidnapp", r"\babduct", r"\bminor .* taken\b", r"\blawful guardianship\b"),
    "sexual_offences": (r"\brape\b", r"\bsexual assault\b", r"\bpocso\b"),
    "dowry": (r"\bdowry\b", r"\bcruelty by husband\b", r"\b498a\b"),
    "conspiracy": (r"\bcriminal conspiracy\b", r"\bcommon intention\b", r"\bshared intention\b"),
    "narcotics": (r"\bndps\b", r"\bnarcotics\b", r"\bdrugs?\b", r"\bganja\b", r"\bheroin\b"),
    "anticipatory_bail": (r"\banticipatory bail\b", r"\bpre-arrest bail\b"),
    "regular_bail": (r"\bregular bail\b",),
    "default_bail": (r"\bdefault bail\b",),
    "quashing": (r"\bquashing\b", r"\bquash fir\b", r"\bfir quashing\b"),
    "arrest_safeguards": (r"\barrest safeguard", r"\bnotice before arrest\b", r"\b41a\b"),
}


def load_section_catalog(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "legalai-section-catalog-v1":
        raise ValueError("unexpected legal section catalog schema_version")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("legal section catalog must contain entries")
    return entries


def predict_legal_sections(query: str, top_k: int = DEFAULT_TOP_K) -> list[PredictedLegalSection]:
    from backend.app.services.query_analysis import analyze_legal_query

    return predict_legal_sections_from_analysis(analyze_legal_query(query), top_k=top_k)


def predict_legal_sections_from_analysis(analysis: LegalQueryAnalysis, top_k: int = DEFAULT_TOP_K) -> list[PredictedLegalSection]:
    top_k = min(top_k, DEFAULT_TOP_K)
    catalog = load_section_catalog()
    regime = analysis.legal_regime or resolve_legal_regime(analysis.original_query).regime
    concepts = detected_concepts(analysis)
    explicit = {(section.statute, normalize_section(section.section)) for section in analysis.explicit_sections}
    scores: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in catalog:
        if entry["statute"] not in REGIME_STATUTES.get(regime, REGIME_STATUTES["unknown"]):
            continue
        concept_hits = sorted(set(entry.get("concepts", [])) & concepts)
        alias_hits = alias_hits_for(analysis.original_query, entry)
        key = (entry["statute"], normalize_section(entry["section"]))
        relationship = explicit_relationship(entry, explicit)
        if not concept_hits and not alias_hits and relationship != "supports_explicit":
            continue
        base_score = 0.55 + 0.2 * len(concept_hits) + 0.1 * len(alias_hits)
        if entry["statute"] in {statute.canonical for statute in analysis.explicit_statutes}:
            base_score += 0.1
        warnings: list[str] = []
        if relationship == "conflicts_with_explicit":
            warnings.append("predicted_section_conflicts_with_explicit_section")
            base_score -= 0.15
        if relationship == "supports_explicit":
            base_score += 0.05
        existing = scores.get(key)
        evidence = [*concept_hits, *[f"alias:{hit}" for hit in alias_hits]]
        if existing is None or base_score > existing["score"]:
            scores[key] = {
                "entry": entry,
                "score": round(min(base_score, 0.99), 3),
                "evidence": evidence,
                "relationship": relationship,
                "warnings": warnings,
            }
    ranked = sorted(scores.values(), key=lambda item: (-item["score"], statute_priority(item["entry"], regime), item["entry"]["statute"], item["entry"]["section"]))[:top_k]
    return [
        PredictedLegalSection(
            statute=item["entry"]["statute"],
            section=item["entry"]["section"],
            normalized_section=normalize_section(item["entry"]["section"]),
            score=item["score"],
            rank=index,
            source="deterministic_baseline",
            confidence=confidence_for_score(item["score"]),
            evidence=item["evidence"],
            prediction_version=PREDICTION_VERSION,
            offence_family=item["entry"].get("offence_family"),
            legal_regime=item["entry"].get("regime"),
            relationship_to_explicit=item["relationship"],
            warnings=item["warnings"],
        )
        for index, item in enumerate(ranked, start=1)
    ]


def detected_concepts(analysis: LegalQueryAnalysis) -> set[str]:
    concepts = {signal.normalized for signal in analysis.offence_family_hints}
    concepts.update(signal.normalized for signal in analysis.procedural_posture)
    text = analysis.original_query.casefold()
    for concept, patterns in CONCEPT_PATTERNS.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            concepts.add(concept)
    return concepts


def alias_hits_for(query: str, entry: dict[str, Any]) -> list[str]:
    text = query.casefold()
    hits = []
    for alias in entry.get("aliases", []):
        alias_text = str(alias).casefold()
        if alias_text and re.search(rf"\b{re.escape(alias_text)}\b", text):
            hits.append(str(alias))
    return hits


def explicit_relationship(entry: dict[str, Any], explicit: set[tuple[str | None, str]]) -> str:
    key = (entry["statute"], normalize_section(entry["section"]))
    if key in explicit:
        return "supports_explicit"
    if not explicit:
        return "supplementary"
    if any(statute == entry["statute"] for statute, _section in explicit):
        return "conflicts_with_explicit"
    return "supplementary"


def normalize_section(section: str) -> str:
    return re.sub(r"\s+", "", section).casefold()


def confidence_for_score(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def statute_priority(entry: dict[str, Any], regime: str) -> int:
    preferred = {
        "ipc_crpc": {"IPC": 0, "CrPC": 0},
        "bns_bnss": {"BNS": 0, "BNSS": 0},
        "mixed_or_transition": {"IPC": 0, "CrPC": 0, "BNS": 0, "BNSS": 0},
        "unknown": defaultdict(lambda: 1),
    }
    mapping = preferred.get(regime, {})
    return mapping.get(entry["statute"], 1) if isinstance(mapping, dict) else 1


def section_key(statute: str, section: str) -> tuple[str, str]:
    return (statute, normalize_section(section))


def evaluate_section_predictions(predicted: list[PredictedLegalSection], gold: list[dict[str, Any]], k: int = 5) -> dict[str, float]:
    """Reusable multi-label metrics for future reviewed section gold."""

    relevant = {
        section_key(item["statute"], item["section"])
        for item in gold
        if item.get("relevance") in {"primary", "relevant"}
    }
    ranked = [section_key(item.statute, item.section) for item in sorted(predicted, key=lambda item: item.rank)[:k]]
    hits = [key in relevant for key in ranked]
    precision_at_1 = sum(hits[:1]) / 1 if ranked[:1] else 0.0
    precision_at_3 = sum(hits[:3]) / 3 if ranked[:3] else 0.0
    precision_at_5 = sum(hits[:5]) / 5 if ranked[:5] else 0.0
    recall_at_5 = sum(hits[:5]) / len(relevant) if relevant else 0.0
    mrr = next((1 / index for index, hit in enumerate(hits, start=1) if hit), 0.0)
    dcg = sum((1.0 if hit else 0.0) / log2_rank(index) for index, hit in enumerate(hits[:5], start=1))
    ideal_hits = [True] * min(len(relevant), 5)
    idcg = sum(1.0 / log2_rank(index) for index, _hit in enumerate(ideal_hits, start=1))
    ndcg = dcg / idcg if idcg else 0.0
    return {
        "precision_at_1": round(precision_at_1, 6),
        "precision_at_3": round(precision_at_3, 6),
        "precision_at_5": round(precision_at_5, 6),
        "recall_at_5": round(recall_at_5, 6),
        "mrr": round(mrr, 6),
        "ndcg_at_5": round(ndcg, 6),
    }


def log2_rank(rank: int) -> float:
    import math

    return math.log2(rank + 1)
