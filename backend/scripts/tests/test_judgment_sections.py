"""Unit tests for judgment section extraction and normalization."""

from __future__ import annotations

import unittest

from backend.app.services.judgment_sections import (
    canonical_section,
    extract_section_mentions,
    prepare_judgment_text,
    regime_for,
    statute_regimes,
)
from backend.scripts.load_ipc_bns import normalize_section_field


class SectionNormalizationTests(unittest.TestCase):
    def test_canonical_section(self) -> None:
        cases = {"302": "302", "0302": "302", "498a": "498A", "304B": "304B", "103(1)": "103", "20(b)(ii)": "20", " 376 D ": "376D"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_section(raw), expected)
        for raw in ("", "Part-II", "A", "120(B)", "506(B)"):  # "(B)": suffix or sub-part? not guessed
            with self.subTest(raw=raw):
                self.assertIsNone(canonical_section(raw))

    def test_text_pre_normalization(self) -> None:
        self.assertEqual(prepare_judgment_text("u/s 302/34 IPC"), "Section 302, 34 IPC")
        self.assertEqual(prepare_judgment_text("Section 302 r/w 34 IPC"), "Section 302, 34 IPC")
        self.assertEqual(prepare_judgment_text("Section 438 Cr.P.C."), "Section 438 CrPC")
        self.assertEqual(prepare_judgment_text("Section 34 I.P.C."), "Section 34 IPC")
        self.assertEqual(prepare_judgment_text("Section 498-A"), "Section 498A")

    def test_loader_section_fields_follow_the_same_convention(self) -> None:
        self.assertEqual(normalize_section_field(" 366-B "), "366B")
        self.assertEqual(normalize_section_field("147-151"), "147-151")  # crime-head range kept
        self.assertEqual(normalize_section_field("376 r/w  511"), "376 r/w 511")
        self.assertIsNone(normalize_section_field("  "))


class SectionExtractionTests(unittest.TestCase):
    def assertMentions(self, text: str, expected: list[tuple[str, str]]) -> None:
        self.assertEqual(extract_section_mentions(text).mentions, expected)

    def test_common_judgment_citation_forms(self) -> None:
        self.assertMentions("convicted under Section 302 of the Indian Penal Code", [("IPC", "302")])
        self.assertMentions("u/s 302/34 IPC", [("IPC", "302"), ("IPC", "34")])
        self.assertMentions("Sections 302, 34 and 201 IPC", [("IPC", "302"), ("IPC", "34"), ("IPC", "201")])
        self.assertMentions("Section 438 Cr.P.C.", [("CrPC", "438")])
        self.assertMentions("Section 20(b)(ii)(C) of the NDPS Act", [("NDPS Act", "20")])
        self.assertMentions("Section 103(1) BNS", [("BNS", "103")])
        self.assertMentions("Section 498-A IPC", [("IPC", "498A")])
        self.assertMentions("Section 498 A IPC", [("IPC", "498A")])

    def test_old_and_new_codes_are_distinguished(self) -> None:
        self.assertMentions("Section 302 IPC and Section 103 BNS", [("IPC", "302"), ("BNS", "103")])
        regimes = statute_regimes()
        self.assertEqual((regime_for("IPC", regimes), regime_for("CrPC", regimes)), ("ipc_crpc", "ipc_crpc"))
        self.assertEqual((regime_for("BNS", regimes), regime_for("BNSS", regimes)), ("bns_bnss", "bns_bnss"))

    def test_sections_are_never_invented(self) -> None:
        unbound = extract_section_mentions("as observed in Section 161 and paragraph 12")
        self.assertEqual(unbound.mentions, [])
        self.assertEqual(unbound.rejected["no_explicit_statute"], 2)  # 161 and 12: neither has a statute
        out_of_range = extract_section_mentions("Section 2024 IPC")
        self.assertEqual(out_of_range.mentions, [])
        self.assertEqual(out_of_range.rejected["out_of_range"], 1)
        self.assertMentions("Section 34 of the Contract Act", [])
        ambiguous = extract_section_mentions("Sections 120(B), 34 IPC")
        self.assertEqual(ambiguous.mentions, [("IPC", "34")])  # 120(B) is not turned into 120
        self.assertEqual(ambiguous.rejected["ambiguous_letter_suffix"], 1)


if __name__ == "__main__":
    unittest.main()
