"""Step 19: the mapping builder verifies TLS, and the printed-pair cross-check classifies and attributes correctly."""

from __future__ import annotations

import csv
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts import build_ipc_bns_mapping as builder  # noqa: E402
from backend.scripts import crosscheck_ipc_bns_pdf_pairs as xcheck  # noqa: E402

CANDIDATES = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv"


class BuilderTlsTests(unittest.TestCase):
    def test_fetch_verifies_the_certificate_chain_and_host_name(self) -> None:
        context = builder.tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        source = (REPO_ROOT / "backend/scripts/build_ipc_bns_mapping.py").read_text(encoding="utf-8")
        self.assertNotIn("_create_unverified_context", source)
        self.assertNotIn("CERT_NONE", source)

    def test_fetch_passes_the_verified_context(self) -> None:
        with patch.object(builder.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"<html></html>"
            builder.fetch("https://example.invalid/page")
        self.assertEqual(urlopen.call_args.kwargs["context"].verify_mode, ssl.CERT_REQUIRED)


def head(ipc: str, bns: str, page: int = 7) -> dict:
    return {"head_printed": f"Head ({bns} BNS / {ipc} IPC)", "ipc_section": ipc, "bns_section": bns, "table_page": page, "pdf_page": page + 47}


class CrosscheckTests(unittest.TestCase):
    MAPPING = {
        "IPC 302": {"exact": {"BNS 103"}, "group": set()},
        "IPC 255": {"exact": set(), "group": {"BNS 212"}},
        "IPC 257": {"exact": set(), "group": {"BNS 181"}},
        "IPC 420": {"exact": {"BNS 999"}, "group": set()},
    }

    def run_check(self, heads: dict) -> dict:
        from backend.app.services.ncrb_sections import row_labels

        stored = {name: (*row_labels(info["ipc_section"], info["bns_section"])[:2], set()) for name, info in heads.items()}
        return {entry["head"]: entry for entry in xcheck.crosscheck(heads, stored, self.MAPPING)}

    def test_statuses_and_evidence_levels(self) -> None:
        results = self.run_check({
            "Murder": head("302", "103(1)"),
            "Stamps": head("255-257", "178-181"),
            "Theft": head("379-380", "303"),
            "Cheating": head("420", "318(4)"),
            "One side": head("", "113"),
        })
        sections = {s["ipc"]: (s["status"], s["level"]) for entry in results.values() for s in entry["sections"]}
        self.assertEqual(sections["IPC 302"], ("covered", "exact"))
        self.assertEqual(sections["IPC 257"], ("covered", "group"))
        self.assertEqual(sections["IPC 255"], ("differs", "group"))  # only a group-label row: not a contradiction
        self.assertEqual(sections["IPC 256"], ("missing", ""))
        self.assertEqual(sections["IPC 420"], ("differs", "exact"))  # a single-section row maps elsewhere
        self.assertEqual(sections["IPC 379"], ("missing", ""))
        self.assertEqual(results["One side"]["status"], "not a pair (one side printed)")
        self.assertEqual(results["Murder"]["status"], "covered")

    def test_candidates_keep_the_printed_group_attribution_and_no_change_type(self) -> None:
        rows = xcheck.candidates(list(self.run_check({"Theft": head("379-382", "303,305-307", page=52)}).values()))
        self.assertEqual([row["bns_section"] for row in rows], ["303", "305", "306", "307"])
        for row in rows:
            self.assertEqual(row["ipc_section"], "379-382")
            self.assertEqual(row["change_type"], "")
            self.assertEqual(row["source"], "NCRB Crime in India 2024, Vol. I, Table 1A.4, p. 52")
            self.assertEqual(row["ipc_description"], "Head (303,305-307 BNS / 379-382 IPC)")

    def test_stored_labels_must_equal_the_printed_text(self) -> None:
        with self.assertRaises(SystemExit):
            xcheck.crosscheck({"Murder": head("302", "103")}, {"Murder": (["IPC 999"], ["BNS 103"], set())}, self.MAPPING)


class CommittedCandidatesTests(unittest.TestCase):
    def test_the_seven_pairs_from_step_15b_are_among_the_candidates(self) -> None:
        rows = list(csv.DictReader(CANDIDATES.open(encoding="utf-8", newline="")))
        pairs = {(row["ipc_section"], row["bns_section"]) for row in rows}
        for pair in [("379-382", "303"), ("384-389", "308"), ("392/394/397", "309"), ("396", "310"),
                     ("406-409", "316"), ("411-414", "317"), ("153A", "196")]:
            with self.subTest(pair=pair):
                self.assertIn(pair, pairs)
        self.assertTrue(all(row["change_type"] == "" and row["source"].startswith("NCRB Crime in India 2024") for row in rows))


if __name__ == "__main__":
    unittest.main()
