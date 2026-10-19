"""Tests for the index_metadata_v1 field derivation (no database)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.index_metadata import (
    FIELDS,
    chunk_index_fields,
    derive_legal_regime,
    index_view,
    sorted_labels,
    store_form,
)
from backend.app.services.vector_store import metadata_for_chroma


class TestIndexMetadata(unittest.TestCase):
    def test_labels_sort_by_statute_then_section_number(self) -> None:
        pairs = {("IPC", "302"), ("IPC", "34"), ("IPC", "120B"), ("IPC", "120"), ("CrPC", "313"), ("BNS", "103")}
        self.assertEqual(sorted_labels(pairs), ["BNS 103", "CrPC 313", "IPC 34", "IPC 120", "IPC 120B", "IPC 302"])

    def test_chunk_fields(self) -> None:
        fields = chunk_index_fields(
            "judgment",
            {("IPC", "302"), ("IPC", "34"), ("CrPC", "313")},
            "Convicted under Section 302 IPC. Statement under Section 313 Cr.P.C. recorded.",
        )
        self.assertEqual(set(fields), set(FIELDS))
        self.assertEqual(fields["cited_sections"], ["CrPC 313", "IPC 34", "IPC 302"])
        self.assertEqual(fields["offence_sections"], ["IPC 302"])
        self.assertEqual(fields["chunk_sections"], ["CrPC 313", "IPC 302"])
        self.assertEqual((fields["cited_section_count"], fields["offence_section_count"], fields["chunk_section_count"]), (3, 1, 2))
        self.assertEqual(fields["index_metadata_version"], "index_metadata_v1")

    def test_empty_lists_are_absent_keys_with_zero_counts(self) -> None:
        fields = chunk_index_fields("statute", set(), "No section is cited here.")
        stored = store_form(fields)
        self.assertIsNone(stored["cited_sections"])
        self.assertEqual(stored["cited_section_count"], 0)
        metadata = metadata_for_chroma(
            {"chunk_id": "c", "document_id": "d", "provider": "p", "source_document_id": "s", "chunk_index": 0,
             "paragraph_start": 0, "paragraph_end": 0, **fields},
            "fingerprint",
        )
        self.assertNotIn("cited_sections", metadata)
        self.assertEqual((metadata["doc_type"], metadata["chunk_section_count"]), ("statute", 0))
        self.assertEqual(index_view(metadata), fields)  # read back: absent list == []

    def test_legal_regime_from_cited_statutes(self) -> None:
        self.assertEqual(derive_legal_regime(["IPC", "CrPC", "Evidence Act"]), "ipc_crpc")
        self.assertEqual(derive_legal_regime(["BNS", "NDPS Act"]), "bns_bnss")
        self.assertEqual(derive_legal_regime(["IPC", "BNSS"]), "mixed_or_transition")
        self.assertEqual(derive_legal_regime(["NDPS Act", "Evidence Act"]), "unknown")
        self.assertEqual(derive_legal_regime([]), "unknown")


if __name__ == "__main__":
    unittest.main()
