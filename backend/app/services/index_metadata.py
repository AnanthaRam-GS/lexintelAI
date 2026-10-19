"""Index metadata derived from PostgreSQL for Chroma and BM25 (``index_metadata_v1``).

PostgreSQL is canonical. These fields are added to every chunk's metadata in
both indexes, by ``backend/scripts/enrich_index_metadata.py`` for existing
chunks and by admin ingestion for new ones, and are checked by
``verify_store_consistency.py``. See ``docs/INDEX_METADATA.md``.

| Field | Level | Type | Source |
|---|---|---|---|
| ``doc_type`` | document | str | ``documents.doc_type`` |
| ``cited_sections`` | document | list[str] | ``document_sections`` labels, e.g. "IPC 302" |
| ``offence_sections`` | document | list[str] | the ``offence`` subset (``provision_types``) |
| ``chunk_sections`` | chunk | list[str] | ``judgment_sections`` extractor on the chunk's PostgreSQL text |
| ``cited_section_count``, ``offence_section_count``, ``chunk_section_count`` | as above | int | list lengths |
| ``index_metadata_version`` | chunk | str | ``index_metadata_v1`` |

Lists are Chroma list metadata (Chroma >= 1.5): filter with
``{"cited_sections": {"$contains": "IPC 302"}}``, an exact element match.
Chroma rejects empty lists, so an empty list is stored as an absent key in
both indexes, and its count is 0. Labels are sorted by statute, then section
number, then suffix.

``effective_legal_regime`` is derived from the cited statutes
(``derive_legal_regime``) only where the index has no value, which is
admin uploads. Curated-corpus chunks keep the reviewed value from the
acquisition manifest. ``effective_offence_family`` cannot be derived: no code
maps sections to the corpus's offence-family vocabulary, so admin uploads
leave it empty.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from backend.app.services.judgment_sections import extract_section_mentions, regime_for, statute_regimes
from backend.app.services.provision_types import is_offence

INDEX_METADATA_VERSION = "index_metadata_v1"
LIST_FIELDS = ("cited_sections", "offence_sections", "chunk_sections")
COUNT_FIELDS = {
    "cited_sections": "cited_section_count",
    "offence_sections": "offence_section_count",
    "chunk_sections": "chunk_section_count",
}
FIELDS = ("doc_type", *LIST_FIELDS, *COUNT_FIELDS.values(), "index_metadata_version")
REGIME_FIELD = "effective_legal_regime"
_SECTION_ORDER = re.compile(r"(\d+)(.*)")


def section_label(statute: str, section: str) -> str:
    return f"{statute} {section}"


def _label_order(label: str) -> tuple:
    statute, _, section = label.rpartition(" ")
    match = _SECTION_ORDER.fullmatch(section)
    return (statute, int(match.group(1)), match.group(2)) if match else (statute, 10**9, section)


def sorted_labels(pairs: Iterable[tuple[str, str]]) -> list[str]:
    return sorted({section_label(statute, section) for statute, section in pairs}, key=_label_order)


def chunk_section_pairs(text: str) -> set[tuple[str, str]]:
    """(statute, section) pairs cited in one chunk, by the document_sections extractor."""
    return set(extract_section_mentions(text).mentions)


def derive_legal_regime(statutes: Iterable[str]) -> str:
    """ipc_crpc / bns_bnss / mixed_or_transition / unknown, from the cited statutes' regimes."""
    regimes = statute_regimes()
    codes = {regime_for(statute, regimes) for statute in statutes} & {"ipc_crpc", "bns_bnss"}
    if len(codes) == 2:
        return "mixed_or_transition"
    return next(iter(codes)) if codes else "unknown"


def chunk_index_fields(doc_type: str, document_pairs: Iterable[tuple[str, str]], chunk_text: str) -> dict[str, Any]:
    """The index_metadata_v1 fields for one chunk; lists may be empty here."""
    pairs = set(document_pairs)
    fields: dict[str, Any] = {
        "doc_type": doc_type,
        "cited_sections": sorted_labels(pairs),
        "offence_sections": sorted_labels(pair for pair in pairs if is_offence(*pair)),
        "chunk_sections": sorted_labels(chunk_section_pairs(chunk_text)),
    }
    for name, count in COUNT_FIELDS.items():
        fields[count] = len(fields[name])
    fields["index_metadata_version"] = INDEX_METADATA_VERSION
    return fields


def store_form(fields: dict[str, Any]) -> dict[str, Any]:
    """Fields as written to the indexes: an empty list becomes None (absent key; Chroma update deletes it)."""
    return {key: (value or None) if key in LIST_FIELDS else value for key, value in fields.items()}


def expected_from_postgres(cursor: Any) -> dict[str, dict[str, Any]]:
    """{chroma_id: {"fields", "derived_regime", "document_key"}} for every PostgreSQL chunk (DB-API cursor, read only)."""
    cursor.execute("SELECT id, doc_type, source_document_key FROM documents")
    documents = {row[0]: (row[1], row[2] or str(row[0])) for row in cursor.fetchall()}
    cursor.execute("SELECT document_id, statute, section FROM document_sections WHERE section <> ''")
    sections: dict[int, set[tuple[str, str]]] = {}
    for document_id, statute, section in cursor.fetchall():
        sections.setdefault(document_id, set()).add((statute, section))
    cursor.execute("SELECT document_id, chroma_id, text FROM chunks WHERE chroma_id IS NOT NULL")
    expected: dict[str, dict[str, Any]] = {}
    for document_id, chroma_id, text in cursor.fetchall():
        doc_type, key = documents[document_id]
        pairs = sections.get(document_id, set())
        expected[chroma_id] = {
            "fields": chunk_index_fields(doc_type, pairs, text),
            "derived_regime": derive_legal_regime(statute for statute, _ in pairs),
            "document_key": key,
        }
    return expected


def index_view(metadata: dict[str, Any]) -> dict[str, Any]:
    """The index_metadata_v1 fields as read back from an index, absent lists as []."""
    view = {key: metadata.get(key) for key in FIELDS}
    for key in LIST_FIELDS:
        view[key] = sorted(view[key] or [], key=_label_order)
    return view
