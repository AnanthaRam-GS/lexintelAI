"""Conservative, rule-based outcome extraction from a judgment's operative part.

Only the concluding chunks are read (``OPERATIVE_CHUNKS``, by chunk index).
Rules match operative, present-tense phrasing, such as "the appeal is
dismissed" or "the appellants are acquitted". These do not match:
- narrated history ("the appeal was dismissed");
- argument ("reasons for acquittal are erroneous");
- conditional phrasing ("liable to be allowed");
- hypothetical or modal clauses ("what if the appellant is acquitted", "I
  would maintain the convictions").

"<person> is convicted under ..." is deliberately not a rule, because
appellate judgments use it to narrate the trial court's decision.

Each field gets one finding:

- ``found``: exactly one value fired; the evidence chunk and rule are kept;
- ``unknown``: no rule fired;
- ``ambiguous``: rules disagree (for example co-accused with different
  results); no value is stored.

Precision matters more than coverage: only ``found`` values are written, and
``unknown``/``ambiguous`` fields stay NULL. Values match the labels
``services/analytics.py`` buckets: conviction_status ``convicted`` or
``acquitted``; appeal_result ``allowed``, ``partly allowed`` or
``dismissed``; case_disposition is a short label such as "appeal dismissed"
or "bail granted".
"""

from __future__ import annotations

from dataclasses import dataclass
import re

OUTCOME_METHOD = "operative_rules_v2"
CONFLICT = "__conflict__"  # rule value that never becomes a stored value
OPERATIVE_CHUNKS = 2
FIELDS = ("conviction_status", "appeal_result", "case_disposition")

_BE = r"(?:is|are|stands?|shall\s+stand)\s+(?:hereby\s+|accordingly\s+|also\s+)?"
_GAP = r"[^.;:]{0,80}?"
_APPEAL = r"\b(?:criminal\s+)?(?:appeals?|revisions?(?:\s+petitions?)?)\b"
_PETITION = r"\b(?:writ\s+)?(?:petitions?|applications?)\b"
_PERSON = r"\b(?:accused(?:\s+persons?)?|appellants?|respondents?|applicants?|petitioners?|they|he|she)\b"
_NUMBER_DOT = re.compile(r"\.(?=\s*\d)")


@dataclass(frozen=True)
class OutcomeRule:
    field: str
    value: str
    name: str
    pattern: re.Pattern[str]


def _rule(field: str, value: str, name: str, pattern: str) -> OutcomeRule:
    return OutcomeRule(field, value, name, re.compile(pattern, re.IGNORECASE))


RULES: tuple[OutcomeRule, ...] = (
    # appeal_result (appeals and criminal revisions)
    _rule("appeal_result", "partly allowed", "appeal_partly_allowed",
          rf"{_APPEAL}{_GAP}\b{_BE}(?:partly|partially)\s+allowed\b|{_APPEAL}{_GAP}\b{_BE}allowed\s+in\s+part\b"
          rf"|\bpartly\s+allow\s+(?:the|this)\s+appeals?\b|\bpartially\s+accept\s+(?:the|this)\s+appeals?\b"),
    _rule("appeal_result", "allowed", "appeal_allowed", rf"{_APPEAL}{_GAP}\b{_BE}allowed\b(?!\s+in\s+part)"),
    _rule("appeal_result", "dismissed", "appeal_dismissed", rf"{_APPEAL}{_GAP}\b{_BE}(?:dismissed|rejected)\b"),
    # conviction_status
    _rule("conviction_status", "convicted", "conviction_upheld",
          rf"\bconvictions?\b{_GAP}\b{_BE}(?:upheld|confirmed|maintained|affirmed)\b"
          r"|\b(?:uphold|upholding|affirm|affirming|maintain|maintaining|confirm|confirming)\s+the\s+convictions?\b"),
    # "<person> is convicted for/under ..." never sets a value, because
    # appellate judgments narrate the trial court's conviction in the present
    # tense. It is a conflict signal: alongside another value it makes the field
    # ambiguous (for example co-accused with different results).
    _rule("conviction_status", CONFLICT, "conviction_narration_conflict",
          rf"{_PERSON}{_GAP}\b{_BE}convicted\s+(?:for|under|of)\b"),
    _rule("conviction_status", "acquitted", "accused_acquitted", rf"{_PERSON}{_GAP}\b{_BE}acquitted\b"),
    # case_disposition (one label; conflicting labels make it ambiguous)
    _rule("case_disposition", "bail granted", "bail_granted",
          rf"\b(?:anticipatory\s+)?bail\b{_GAP}\b{_BE}(?:granted|allowed)\b"),
    _rule("case_disposition", "bail refused", "bail_refused",
          rf"\b(?:anticipatory\s+)?bail\b{_GAP}\b{_BE}(?:refused|rejected|dismissed|declined)\b"),
    _rule("case_disposition", "proceedings quashed", "proceedings_quashed",
          rf"\b(?:FIR|proceedings?|charge[\s-]?sheet|complaint|summoning\s+order|cognizance\s+order)\b{_GAP}\b{_BE}"
          r"(?:quashed|quashed\s+and\s+set\s+aside|set\s+aside\s+and\s+quashed)\b"),
    _rule("case_disposition", "remanded", "matter_remanded",
          rf"\b(?:matters?|cases?|appeals?)\b{_GAP}\b{_BE}(?:remanded|remitted)\b"),
    _rule("case_disposition", "appeal partly allowed", "disposition_appeal_partly_allowed",
          rf"{_APPEAL}{_GAP}\b{_BE}(?:partly|partially)\s+allowed\b|{_APPEAL}{_GAP}\b{_BE}allowed\s+in\s+part\b"),
    _rule("case_disposition", "appeal allowed", "disposition_appeal_allowed", rf"{_APPEAL}{_GAP}\b{_BE}allowed\b(?!\s+in\s+part)"),
    _rule("case_disposition", "appeal dismissed", "disposition_appeal_dismissed", rf"{_APPEAL}{_GAP}\b{_BE}(?:dismissed|rejected)\b"),
    _rule("case_disposition", "petition allowed", "petition_allowed", rf"{_PETITION}{_GAP}\b{_BE}allowed\b"),
    _rule("case_disposition", "petition dismissed", "petition_dismissed", rf"{_PETITION}{_GAP}\b{_BE}(?:dismissed|rejected)\b"),
    _rule("case_disposition", "acquitted", "disposition_acquitted", rf"{_PERSON}{_GAP}\b{_BE}acquitted\b"),
)

# A match inside a hypothetical or modal clause ("what if the appellant is
# acquitted", "I would maintain the convictions") is not an operative order.
_NON_OPERATIVE_CONTEXT = re.compile(
    r"\b(?:if|whether|unless|in\s+case|in\s+the\s+event|would|should|could|might|may|assum\w*|suppos\w*)\b",
    re.IGNORECASE,
)
_CLAUSE_LOOKBACK = 120


def _is_operative(flat: str, start: int) -> bool:
    boundary = max(flat.rfind(". ", 0, start), flat.rfind("; ", 0, start), flat.rfind(": ", 0, start), start - _CLAUSE_LOOKBACK)
    return not _NON_OPERATIVE_CONTEXT.search(flat[max(0, boundary): start])

# A disposition label from a specific rule supersedes a generic one it implies.
_DISPOSITION_SUPERSEDES = {
    "bail granted": {"petition allowed"},
    "bail refused": {"petition dismissed"},
    "proceedings quashed": {"petition allowed"},
    "appeal allowed": {"acquitted"},
}


@dataclass(frozen=True)
class OutcomeFinding:
    field: str
    status: str  # found | unknown | ambiguous
    value: str | None = None
    rule: str | None = None
    chunk_id: str | None = None
    start: int | None = None
    end: int | None = None
    candidates: tuple[str, ...] = ()


def operative_chunks(chunks: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    """(chunk_id, text) for the concluding chunks, given (chunk_index, chunk_id, text)."""
    return [(chunk_id, text) for _index, chunk_id, text in sorted(chunks)[-OPERATIVE_CHUNKS:]]


def extract_outcomes(operative: list[tuple[str, str]]) -> dict[str, OutcomeFinding]:
    matches: dict[str, list[tuple[OutcomeRule, str, re.Match[str]]]] = {name: [] for name in FIELDS}
    for chunk_id, text in operative:
        # "Accused No. 1", "Appeal No. 160": a dot before a digit is not a sentence end.
        flat = _NUMBER_DOT.sub(" ", " ".join(text.split()))
        for rule in RULES:
            for match in rule.pattern.finditer(flat):
                if _is_operative(flat, match.start()):
                    matches[rule.field].append((rule, chunk_id, match))
    findings = {name: _resolve(name, matches[name]) for name in FIELDS}
    disposition, conviction = findings["case_disposition"], findings["conviction_status"]
    if disposition.value == "acquitted" and conviction.value != "acquitted":
        # One acquitted co-accused does not make the case an acquittal.
        findings["case_disposition"] = OutcomeFinding(
            "case_disposition", "ambiguous", candidates=("acquitted", f"conviction_status_{conviction.status}")
        )
    return findings


def _resolve(field: str, hits: list[tuple[OutcomeRule, str, re.Match[str]]]) -> OutcomeFinding:
    if not hits:
        return OutcomeFinding(field, "unknown")
    values = {rule.value for rule, _, _ in hits}
    if values == {CONFLICT}:
        return OutcomeFinding(field, "unknown")
    if CONFLICT in values:
        return OutcomeFinding(field, "ambiguous", candidates=tuple(sorted(v for v in values if v != CONFLICT)) + ("conflicting_narration",))
    if field == "case_disposition":
        values = {value for value in values if not any(value in _DISPOSITION_SUPERSEDES.get(other, set()) for other in values)}
    if field == "appeal_result" and values == {"partly allowed", "allowed"}:
        values = {"partly allowed"}  # "partly allowed ... allowed qua A2" is a partial outcome
    if len(values) != 1:
        return OutcomeFinding(field, "ambiguous", candidates=tuple(sorted(values)))
    value = next(iter(values))
    rule, chunk_id, match = next((r, c, m) for r, c, m in hits if r.value == value)
    return OutcomeFinding(field, "found", value, rule.name, chunk_id, match.start(), match.end())
