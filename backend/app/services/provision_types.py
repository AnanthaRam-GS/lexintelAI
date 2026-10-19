"""Provision-type classification for cited statutory sections.

The legal section catalog (``legal_section_catalog.json``) has no
provision-type field, so this module provides an explicit classification by
statute chapter. Analytics count only ``offence`` provisions by default.

| Type | Meaning | Examples |
|---|---|---|
| ``offence`` | Substantive offence or penal section | IPC 302, 376, 120B; BNS 103; NDPS 20; POCSO 4 |
| ``liability_linking`` | Attaches liability to another offence | IPC 34, 35, 37, 38, 107-117 (abetment), 149, 511 (attempt); BNS 45-60, 62, 190 |
| ``definitional_general`` | Definitions, general explanations, punishments in general, general exceptions | IPC 1-75, 76-106, 120A; BNS 1-44 |
| ``procedural`` | Procedure | all CrPC and BNSS; special-Act procedure |
| ``evidentiary`` | Evidence law | Evidence Act |

The chapter boundaries follow the statutes' own chapters (IPC 1860, BNS
2023, NDPS Act 1985, POCSO Act 2012, SC/ST (Prevention of Atrocities) Act
1989). Sections outside a known range are ``unclassified`` and are not
counted as offences.
"""

from __future__ import annotations

import re

CLASSIFICATION_VERSION = "provision_types_v1"
OFFENCE = "offence"
PROVISION_TYPES = ("offence", "liability_linking", "definitional_general", "procedural", "evidentiary", "unclassified")

_SECTION = re.compile(r"(\d+)([A-Z]?)")


def _parts(section: str) -> tuple[int, str] | None:
    match = _SECTION.fullmatch(section)
    return (int(match.group(1)), match.group(2)) if match else None


_IPC_SUFFIXED_UP_TO_120 = {"52A", "108A", "120A", "120B"}


def _ipc(number: int, suffix: str) -> str:
    if number <= 120 and suffix and f"{number}{suffix}" not in _IPC_SUFFIXED_UP_TO_120:
        return "unclassified"  # no such IPC section, e.g. Evidence Act 113B bound to IPC
    if number in (34, 35, 37, 38) and not suffix:
        return "liability_linking"  # common intention and joint acts (Chapter II)
    if number <= 52:
        return "definitional_general"  # Chapters I-II: introduction, general explanations (incl. 52A)
    if number <= 75:
        return "definitional_general"  # Chapter III: of punishments
    if number <= 106:
        return "definitional_general"  # Chapter IV: general exceptions
    if number <= 117:
        return "liability_linking"  # Chapter V: abetment (107-117)
    if number <= 119 or (number == 120 and not suffix):
        return OFFENCE  # Chapter V: concealing a design to commit an offence (118-120)
    if number == 120 and suffix == "A":
        return "definitional_general"  # 120A defines criminal conspiracy
    if number == 120 and suffix == "B":
        return OFFENCE  # 120B punishes criminal conspiracy
    if number == 149 and not suffix:
        return "liability_linking"  # common object of an unlawful assembly
    if number == 511 and not suffix:
        return "liability_linking"  # Chapter XXIII: attempts
    if number <= 510:
        return OFFENCE  # Chapters VI-XXII: offences
    return "unclassified"


def _bns(number: int, suffix: str) -> str:
    if number <= 13:
        return "definitional_general"  # Chapters I-II: preliminary, punishments
    if number <= 44:
        return "definitional_general"  # Chapter III: general exceptions
    if number <= 60:
        return "liability_linking"  # Chapter IV: abetment
    if number == 61:
        return OFFENCE  # criminal conspiracy
    if number == 62:
        return "liability_linking"  # attempt
    if number == 190:
        return "liability_linking"  # common object of an unlawful assembly
    if number <= 358:
        return OFFENCE  # Chapters V-XX: offences
    return "unclassified"


def _ndps(number: int, _suffix: str) -> str:
    if number <= 14:
        return "definitional_general"  # Chapters I-III: definitions, authorities, prohibitions
    if number == 29:
        return "liability_linking"  # abetment and criminal conspiracy
    if number <= 33:
        return OFFENCE  # Chapter IV: offences and penalties (15-33)
    if number <= 40:
        return "definitional_general"  # Chapter IV: presumptions, special courts, other general provisions
    return "procedural"  # Chapter V onwards: procedure


def _pocso(number: int, _suffix: str) -> str:
    if number <= 2:
        return "definitional_general"
    if 16 <= number <= 18:
        return "liability_linking"  # abetment (16-17) and attempt (18)
    if number <= 22:
        return OFFENCE  # Chapters II-V: sexual offences, pornography, reporting offences
    return "procedural"  # Chapters VI onwards: procedure and special courts


def _scst(number: int, _suffix: str) -> str:
    if number <= 2:
        return "definitional_general"
    if number in (3, 4):
        return OFFENCE  # atrocities (3) and neglect of duties (4)
    if number <= 9:
        return "definitional_general"  # enhanced punishment, application of IPC, presumptions, powers
    return "procedural"


_RULES = {"IPC": _ipc, "BNS": _bns, "NDPS Act": _ndps, "POCSO Act": _pocso, "SC/ST Act": _scst}


def provision_type(statute: str, section: str) -> str:
    """Classify a canonical (statute, section) pair, e.g. ("IPC", "302") -> "offence"."""
    if statute in {"CrPC", "BNSS"}:
        return "procedural"
    if statute == "Evidence Act":
        return "evidentiary"
    rule = _RULES.get(statute)
    parts = _parts(section)
    if rule is None or parts is None:
        return "unclassified"
    return rule(*parts)


def is_offence(statute: str | None, section: str) -> bool:
    return bool(statute) and provision_type(statute, section) == OFFENCE
