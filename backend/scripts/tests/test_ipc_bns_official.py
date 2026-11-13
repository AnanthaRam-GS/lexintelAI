"""Step 26b: the IPC-BNS analytics rows carry the official headings and flag conflicting mapping descriptions (no DB)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.app.services import analytics


class FakeQuery:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def query(self, _model):
        return FakeQuery(self.rows)


def row(ipc_section, ipc_description, bns_section, bns_description, source="CYTRAIN"):
    return SimpleNamespace(ipc_section=ipc_section, ipc_description=ipc_description, bns_section=bns_section,
                           bns_description=bns_description, change_type="DIRECT", source=source, source_page=None)


class IpcBnsOfficialHeadingTests(unittest.TestCase):
    def rows(self, *items):
        return analytics.get_ipc_bns_mappings(FakeSession(list(items)))

    def test_official_headings_are_added_and_descriptions_kept(self) -> None:
        [result] = self.rows(row("302", "Punishment for murder.", "103(1)", "Whoever commits murder shall be punished ..."))
        self.assertEqual((result.ipc_official_heading, result.bns_official_heading), ("Punishment for murder", "Punishment for murder"))
        self.assertEqual(result.ipc_description, "Punishment for murder.")  # the source text is not edited
        self.assertFalse(result.ipc_description_conflicts_with_official or result.bns_description_conflicts_with_official)

    def test_listed_conflicting_descriptions_are_flagged(self) -> None:
        results = self.rows(
            row("366B", "Kidnapping, abducting or inducing woman to compel her marriage, etc.", "87", "Kidnapping, abducting or inducing woman ..."),
            row("376", "Gang rape.", "70", "Gang rape."),
            row("376", "Punishment for rape.", "64", "Punishment for rape."),
        )
        self.assertEqual([r.ipc_description_conflicts_with_official for r in results], [True, True, False])
        self.assertEqual(results[0].ipc_official_heading, "Importation of girl from foreign country")
        self.assertEqual(results[1].ipc_official_heading, "Punishment for rape")
        self.assertFalse(any(r.bns_description_conflicts_with_official for r in results))

    def test_a_flag_needs_the_same_row(self) -> None:
        # The same description under another source or section is not flagged.
        results = self.rows(row("376", "Gang rape.", "70", "Gang rape.", source="NCRB_CII_2024_T1A4"), row("376D", "Gang rape.", "70", "Gang rape."))
        self.assertEqual([r.ipc_description_conflicts_with_official for r in results], [False, False])

    def test_group_labels_and_missing_sections_have_no_heading(self) -> None:
        [result] = self.rows(row("415 to 420, 424", "Cheating ...", None, None))
        self.assertEqual((result.ipc_official_heading, result.bns_official_heading), (None, None))

    def test_sub_sections_take_the_section_heading(self) -> None:
        self.assertEqual(analytics.official_heading("BNS", "65(2)"), "Punishment for rape in certain cases")
        self.assertEqual(analytics.official_heading("IPC", "366-B"), "Importation of girl from foreign country")


if __name__ == "__main__":
    unittest.main()
