"""NCRB Table 1A.4 re-extraction (step 15): citation parsing, naming, the arithmetic validator, and the
committed v2 CSV. No database, no network.

Tests that read the source PDF skip, with the reason, when it is absent: it is not committed
(data/raw/ncrb/*.pdf is gitignored; see data/raw/ncrb/SOURCES.md to obtain it).
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts import extract_ncrb_table as extractor
from backend.scripts import validate_ncrb_table as validator

V2_CSV = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_v2.csv"
OLD_CSV = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_complete.csv"
PDF = extractor.DEFAULT_PDF
PDF_OK = PDF.exists() and hashlib.sha256(PDF.read_bytes()).hexdigest() == extractor.EXPECTED_SHA256
REQUIRES_PDF = unittest.skipUnless(
    PDF_OK, f"source PDF not present (or not the recorded Volume I): {PDF.relative_to(REPO_ROOT)} is gitignored; see data/raw/ncrb/SOURCES.md"
)


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CitationParsingTests(unittest.TestCase):
    """Printed head texts from the PDF, with NCRB's own inconsistencies."""

    CASES = {
        "Murder (Section 103 (1) BNS /Section 302 IPC) (Total a+b+c)": ("Murder (Total a+b+c)", "302", "103(1)"),
        "Attempt to Commit Rape (Section 64-68,70- 71 r/w Sec 62 BNS Sec 376 r/w 511 IPC)": ("Attempt to Commit Rape", "376 r/w 511", "64-68,70-71 r/w 62"),
        "Extortion (Section 308 BNS)/Section 384-389 IPC)": ("Extortion", "384-389", "308"),
        "Wrongful Restraint/Confinement (126 & 127 BNS)/Section 341 to 348 IPC": ("Wrongful Restraint/Confinement", "341 to 348", "126 & 127"),
        "Offences relating to Elections (Section 173 to 177 BNS/Sections 171-E to 171-I IPC)": ("Offences relating to Elections", "171-E to 171-I", "173 to 177"),
        "a) Fraud (Section 318(4) r/w Section 336(2)(3)(4), 340(2) BNS/IT Act/Section 420 r/w 465,468- 471 IPC/IT Act)":
            ("a) Fraud", "420 r/w 465,468-471/IT Act", "318(4) r/w 336(2)(3)(4), 340(2)/IT Act"),
        "Circulate False/Fake News/Rumours (Section 353 BNS/ Section 353 r/w IT Act/Section 505 IPC r/w IT Act)":
            ("Circulate False/Fake News/Rumours", "505 r/w IT Act", "353/353 r/w IT Act"),
        "i) Other Sections of Hurt (Section 119 (1) (2),120(1) (2),122(2) & 123 BNS) & (Section 327-331, 334-335 IPC)":
            ("i) Other Sections of Hurt", "327-331, 334-335", "119(1)(2),120(1)(2),122(2) & 123"),
        "b) Murder by Group (of 5 or more persons) (Section 103 (2) BNS)": ("b) Murder by Group (of 5 or more persons)", None, "103(2)"),
        # Cut off by the source: no sections are guessed.
        "e) Voluntarily Causing hurt or Grievous Hurt/Assault or Criminal force to deter public servant from his duty (Section 121(1)/121/(2) or":
            ("e) Voluntarily Causing hurt or Grievous Hurt/Assault or Criminal force to deter public servant from his duty", None, None),
        "Rioting (Total a to r)": ("Rioting (Total a to r)", None, None),
    }

    def test_printed_citations_are_split_into_name_and_sections(self) -> None:
        for printed, expected in self.CASES.items():
            with self.subTest(printed=printed):
                self.assertEqual(extractor.split_citation(printed), expected)

    def test_head_names_join_parents_and_inherit_sections(self) -> None:
        self.assertEqual(
            extractor.head_name(["Offences affecting Human Body", "Murder", "a) Murder (Section 103 (1) BNS/Section 302 IPC)"]),
            ("Offences affecting Human Body", "Murder - a) Murder", "302", "103(1)"),
        )
        self.assertEqual(  # the subtotal repeats its parent without the letter
            extractor.head_name(["Offences Relating to Documents & Property Marks", "Forgery, Cheating & Fraud",
                                 "a) Fraud (Section 318(4) BNS/Section 420 IPC)", "Fraud (Total i+ii+iii+iv)"]),
            ("Offences Relating to Documents & Property Marks", "Forgery, Cheating & Fraud - a) Fraud (Total i+ii+iii+iv)", "420", "318(4)"),
        )
        self.assertEqual(  # a printed stray ")" is dropped; a marker's ")" is not a stray bracket
            extractor.head_name(["Offences against Women and Child", "Cheating by Impersonation (Section 319 BNS/Section 419 IPC))"])[1],
            "Cheating by Impersonation",
        )


class ValidatorTests(unittest.TestCase):
    def run_validator(self, csv_path: Path) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = validator.main(["--csv", str(csv_path), "--skip-table-1a1"])
        return code, out.getvalue()

    def test_committed_v2_passes_every_arithmetic_check(self) -> None:
        code, output = self.run_validator(V2_CSV)
        self.assertEqual(code, 0, output)
        self.assertIn("exceptions: 0", output)

    def test_a_changed_cell_is_reported_with_its_page(self) -> None:
        data = rows(V2_CSV)
        for row in data:
            if row["state"] == "Goa" and row["offense_category"] == "Murder - a) Murder":
                row["case_count"] = row["cases_total"] = "31"  # one murder too many
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupted.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
            code, output = self.run_validator(path)
        self.assertEqual(code, 1)
        self.assertIn("pdf 63 | Goa | Murder - a) Murder | Total | expected 30 actual 31", output)
        self.assertIn("TOTAL STATE(S) | Murder - a) Murder", output)
        self.assertIn("Goa | Murder (Total a+b+c) | case_count | expected 31 actual 30", output)

    def test_the_old_csv_fails_the_same_checks(self) -> None:
        # The step 8 finding: Public Tranquillity's total equals its parts in only 1 of 36 states.
        old = rows(OLD_CSV)
        by = {(row["state"], row["offense_category"]): row["case_count"] for row in old}
        states = sorted({row["state"] for row in old if not row["state"].startswith("TOTAL")})
        parts = ("Unlawful Assembly", "Rioting (Total a to m)", "Affray")
        consistent = [s for s in states if all(by.get((s, p)) for p in parts) and by.get((s, "Total Offences against Public Tranquillity"))
                      and sum(int(by[(s, p)]) for p in parts) == int(by[(s, "Total Offences against Public Tranquillity")])]
        self.assertEqual(consistent, ["Mizoram"])


class CommittedV2Tests(unittest.TestCase):
    def test_shape_and_null_policy(self) -> None:
        data = rows(V2_CSV)
        self.assertEqual(len(data), 159 * 39)
        self.assertEqual(len({row["state"] for row in data}), 39)
        self.assertTrue(all(row["conviction_count"] == "" and row["acquittal_count"] == "" for row in data))  # not in Table 1A.4
        self.assertFalse(any(row["case_count"] == "0" and row["cases_total"] == "" and row["cases_ipc_plus_bns"] == "" and row["cases_ipc"] == "" for row in data))

    def test_goa_and_public_tranquillity_examples(self) -> None:
        by = {(row["state"], row["offense_category"]): row for row in rows(V2_CSV)}
        goa = lambda head: by[("Goa", head)]["case_count"]  # noqa: E731
        self.assertEqual((goa("Murder (Total a+b+c)"), goa("Murder - a) Murder"), goa("Murder - b) Murder by Group (of 5 or more persons)")), ("30", "30", "0"))
        self.assertEqual((by[("Goa", "Murder - a) Murder")]["bns_section"], by[("Goa", "Murder - b) Murder by Group (of 5 or more persons)")]["bns_section"]), ("103(1)", "103(2)"))
        self.assertEqual(goa("Offences against Public Tranquillity (Total)"), "58")


@REQUIRES_PDF
class ReproducibilityTests(unittest.TestCase):
    def test_extraction_reproduces_the_committed_csvs_and_validates_against_table_1a1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(extractor.main(["--out-dir", directory]), 0)
            for name in ("ncrb_stats_2024_v2.csv", "ncrb_2024_table_1A4_v2_cells.csv"):
                self.assertEqual((Path(directory) / name).read_bytes(), (V2_CSV.parent / name).read_bytes(), name)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(validator.main(["--csv", str(V2_CSV)]), 0, out.getvalue())
        self.assertIn("Table 1A.1 cross-check (Total Cognizable IPC/BNS crimes): 117 checks, 0 exceptions", out.getvalue())

    def test_a_different_pdf_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other.pdf"
            shutil.copyfile(PDF, other)
            with other.open("ab") as handle:
                handle.write(b"\n%changed")
            with self.assertRaises(SystemExit):
                extractor.main(["--pdf", str(other), "--out-dir", directory])


if __name__ == "__main__":
    unittest.main()
