"""Tests for the provision-type classification used by analytics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.provision_types import PROVISION_TYPES, is_offence, provision_type


class TestProvisionTypes(unittest.TestCase):
    def assertTypes(self, expected: dict[tuple[str, str], str]) -> None:
        for (statute, section), kind in expected.items():
            with self.subTest(statute=statute, section=section):
                self.assertEqual(provision_type(statute, section), kind)
                self.assertIn(kind, PROVISION_TYPES)

    def test_ipc(self) -> None:
        self.assertTypes({
            ("IPC", "302"): "offence",
            ("IPC", "376"): "offence",
            ("IPC", "498A"): "offence",
            ("IPC", "120B"): "offence",
            ("IPC", "118"): "offence",
            ("IPC", "34"): "liability_linking",
            ("IPC", "149"): "liability_linking",
            ("IPC", "109"): "liability_linking",
            ("IPC", "511"): "liability_linking",
            ("IPC", "2"): "definitional_general",
            ("IPC", "52A"): "definitional_general",
            ("IPC", "53"): "definitional_general",
            ("IPC", "100"): "definitional_general",
            ("IPC", "120A"): "definitional_general",
            ("IPC", "113B"): "unclassified",  # Evidence Act 113B mis-bound to IPC: not an IPC section
            ("IPC", "600"): "unclassified",
        })

    def test_bns_and_procedure(self) -> None:
        self.assertTypes({
            ("BNS", "103"): "offence",
            ("BNS", "61"): "offence",
            ("BNS", "3"): "definitional_general",
            ("BNS", "45"): "liability_linking",
            ("BNS", "190"): "liability_linking",
            ("BNS", "400"): "unclassified",
            ("CrPC", "313"): "procedural",
            ("CrPC", "482"): "procedural",
            ("BNSS", "528"): "procedural",
            ("Evidence Act", "113B"): "evidentiary",
        })

    def test_special_acts(self) -> None:
        self.assertTypes({
            ("NDPS Act", "20"): "offence",
            ("NDPS Act", "29"): "liability_linking",
            ("NDPS Act", "2"): "definitional_general",
            ("NDPS Act", "37"): "definitional_general",
            ("NDPS Act", "50"): "procedural",
            ("POCSO Act", "4"): "offence",
            ("POCSO Act", "17"): "liability_linking",
            ("POCSO Act", "29"): "procedural",
            ("SC/ST Act", "3"): "offence",
            ("SC/ST Act", "8"): "definitional_general",
            ("SC/ST Act", "14"): "procedural",
        })

    def test_unknown_statutes_and_malformed_sections_are_not_offences(self) -> None:
        self.assertEqual(provision_type("Arms Act", "25"), "unclassified")
        self.assertEqual(provision_type("IPC", "302x"), "unclassified")
        self.assertEqual(provision_type("IPC", ""), "unclassified")
        self.assertFalse(is_offence(None, "302"))
        self.assertFalse(is_offence("", "302"))
        self.assertTrue(is_offence("IPC", "302"))
        self.assertFalse(is_offence("IPC", "34"))


if __name__ == "__main__":
    unittest.main()
