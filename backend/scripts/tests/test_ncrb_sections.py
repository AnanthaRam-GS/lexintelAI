"""NCRB section labels and display overrides (step 15b). No database."""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.judgment_sections import canonical_section
from backend.app.services.ncrb_display import DISPLAY_OVERRIDES, display_offense_category
from backend.app.services.ncrb_sections import row_labels, section_labels
from backend.scripts.load_ipc_bns import normalize_section_field

V2_CSV = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_v2.csv"


class SectionLabelTests(unittest.TestCase):
    CASES = {
        ("305/306", "IPC"): ["IPC 305", "IPC 306"],
        ("317 & 318", "IPC"): ["IPC 317", "IPC 318"],
        ("89 and 90", "BNS"): ["BNS 89", "BNS 90"],
        ("64 to 71", "BNS"): [f"BNS {n}" for n in range(64, 72)],
        ("64-68,70-71 r/w 62", "BNS"): ["BNS 64", "BNS 65", "BNS 66", "BNS 67", "BNS 68", "BNS 70", "BNS 71", "BNS 62"],
        ("376 r/w 511", "IPC"): ["IPC 376", "IPC 511"],
        ("498A", "IPC"): ["IPC 498A"],
        ("103(1)", "BNS"): ["BNS 103"],  # subsections dropped, as in document_sections
        ("310(2 & 3)/311", "BNS"): ["BNS 310", "BNS 311"],  # the "&" inside the subsection does not split
        ("171E to 171I", "IPC"): ["IPC 171E", "IPC 171F", "IPC 171G", "IPC 171H", "IPC 171I"],
        ("420 r/w 465,468-471/IT Act", "IPC"): ["IPC 420", "IPC 465", "IPC 468", "IPC 469", "IPC 470", "IPC 471"],
        ("314 / 315 r/w other Crimes", "BNS"): ["BNS 314", "BNS 315"],
    }

    def test_printed_notations(self) -> None:
        for (text, statute), expected in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(section_labels(text, statute), (expected, []))

    def test_unparseable_notation_is_reported_not_guessed(self) -> None:
        self.assertEqual(section_labels("447-252", "IPC"), ([], ["447-252"]))  # a descending range as printed
        self.assertEqual(section_labels("326(f),326(G) & 327(2)", "BNS"), (["BNS 326", "BNS 327"], ["326(G)"]))
        self.assertEqual(section_labels("600", "IPC"), ([], ["600"]))  # out of the IPC range (511)
        self.assertEqual(row_labels(None, None), (None, None, []))

    def test_labels_use_the_document_sections_form(self) -> None:
        for raw in ("0302", "498a", "103(1)", "498A"):
            label = section_labels(raw, "IPC")[0][0]
            self.assertEqual(label, f"IPC {canonical_section(raw)}")

    def test_every_printed_value_in_the_corrected_table(self) -> None:
        rows = list(csv.DictReader(V2_CSV.open(encoding="utf-8")))
        unparsed = set()
        for row in rows:
            _ipc, _bns, notes = row_labels(normalize_section_field(row["ipc_section"]), normalize_section_field(row["bns_section"]))
            unparsed.update(notes)
        self.assertEqual(unparsed, {"IPC: 447-252", "BNS: 326(G)"})


class DisplayOverrideTests(unittest.TestCase):
    def test_only_the_evident_printing_error_is_overridden(self) -> None:
        self.assertEqual(DISPLAY_OVERRIDES, {"Rioting - n) ElectriState/UT/Power Supply Disputes": "Rioting - n) Electricity/Power Supply Disputes"})
        self.assertEqual(display_offense_category("Murder - a) Murder"), "Murder - a) Murder")
        heads = {row["offense_category"] for row in csv.DictReader(V2_CSV.open(encoding="utf-8"))}
        self.assertLessEqual(set(DISPLAY_OVERRIDES), heads)  # the raw head is still exactly as printed


if __name__ == "__main__":
    unittest.main()
