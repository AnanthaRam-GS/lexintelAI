"""Step 25: section labels in answers and briefs are resolved against the trusted sources (services/section_labels.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.api import query as query_api  # noqa: E402
from backend.app.services import section_labels  # noqa: E402
from backend.app.services.legal_answer_generation import (  # noqa: E402
    AnswerMode,
    GroundingStatus,
    LegalAnswerResult,
    ModelGenerationMetadata,
    ProfessionalLegalBrief,
    PublicLegalAnswer,
)
from backend.app.services.section_labels import build_sources, display_text, resolve_provision, resolve_provisions  # noqa: E402

# Exactly as the model wrote them in the docs-site screenshot brief (synthetic FIR, 2026-11-08).
KNOWN_ERRORS = {
    "robbery": "Section 309(4) BNS – offences relating to suicide attempts.",
    "hurt": "Section 115(2) BNS – provisions on medical examination of complainant.",
    "fir": "Section 173 BNS – registration of FIR.",
}


# Step 26 added official headings as the first source. The step 25 tests below check the catalog/mapping logic exactly
# as written then, so they run against the step 25 sources (no official headings); the known errors are checked again
# with the official headings in KnownErrorsWithOfficialHeadingsTests.
STEP25_SOURCES = build_sources(heading_rows=[])


class Step25Sources(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(section_labels, "default_sources", lambda: STEP25_SOURCES)
        patcher.start()
        self.addCleanup(patcher.stop)


def one(text: str, sources=None):
    references = resolve_provision(text, sources)
    assert len(references) == 1, references
    return references[0]


class KnownErrorRegressionTests(Step25Sources):
    def test_bns_309_4_is_robbery_not_suicide(self) -> None:
        reference = one(KNOWN_ERRORS["robbery"])
        self.assertEqual((reference.statute, reference.section), ("BNS", "309(4)"))
        self.assertEqual((reference.label.state, reference.label.title, reference.label.source),
                         ("verified", "Robbery", "section_catalog"))
        self.assertEqual(reference.label.source_key, "BNS 309")
        # Step 26b: the answer's label is kept for audit and flagged; it is never displayed as the title.
        self.assertEqual((reference.label.model_label, reference.label.model_label_differs), ("offences relating to suicide attempts", True))
        self.assertIn("does not match", reference.label.note)
        self.assertEqual(display_text(reference), "Section 309(4) BNS — Robbery (the answer's own label differs)")
        self.assertNotIn("suicide", display_text(reference))

    def test_bns_115_2_is_voluntarily_causing_hurt(self) -> None:
        reference = one(KNOWN_ERRORS["hurt"])
        self.assertEqual((reference.statute, reference.section, reference.label.state), ("BNS", "115(2)", "verified"))
        self.assertTrue(reference.label.title.startswith("Voluntarily causing hurt"))
        self.assertNotIn("medical", display_text(reference))

    def test_173_registration_of_fir_is_corrected_to_the_bnss(self) -> None:
        reference = one(KNOWN_ERRORS["fir"])
        self.assertEqual((reference.statute, reference.section), ("BNSS", "173"))
        label = reference.label
        self.assertEqual((label.state, label.statute_corrected_from), ("corrected_statute", "BNS"))
        self.assertIn("BNSS", label.note)
        # The catalog has BNSS 173(4), not a title for BNSS 173 itself: no title is invented, the label stays unverified.
        self.assertIsNone(label.title)
        self.assertEqual(label.model_label, "registration of FIR")
        self.assertEqual(display_text(reference),
                         "Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified label)")


class StateTests(Step25Sources):
    def test_no_trusted_title_is_unverified_and_keeps_the_model_label_marked(self) -> None:
        reference = one("Section 113B Evidence Act – presumption as to dowry death")
        self.assertEqual((reference.statute, reference.section), ("Evidence Act", "113B"))
        self.assertEqual(reference.label.state, "unverified")
        self.assertIsNone(reference.label.title)  # never invented
        self.assertEqual(reference.label.model_label, "presumption as to dowry death")
        self.assertEqual(display_text(reference), "Section 113B Evidence Act — presumption as to dowry death (unverified label)")

    def test_unverified_without_a_label(self) -> None:
        reference = one("Section 480 BNSS")
        self.assertEqual((reference.label.state, reference.label.title, reference.label.model_label), ("unverified", None, None))
        self.assertEqual(display_text(reference), "Section 480 BNSS (no trusted title)")

    def test_unparseable_text_is_shown_as_written_and_marked(self) -> None:
        reference = one("Trade Marks Act section 18")
        self.assertEqual((reference.statute, reference.label.state), ("Unspecified", "unverified"))
        self.assertEqual(display_text(reference), "Trade Marks Act section 18 (unverified label)")

    def test_a_source_that_disagrees_with_itself_is_a_conflict_with_no_title(self) -> None:
        sources = build_sources(catalog=[], mapping_rows=[
            {"ipc_section": "999", "ipc_description": "First title.", "bns_section": "900", "bns_description": "First title."},
            {"ipc_section": "999", "ipc_description": "Second title.", "bns_section": "900", "bns_description": "Second title."},
        ])
        reference = one("Section 900 BNS – first title", sources)
        self.assertEqual((reference.label.state, reference.label.title), ("conflict", None))
        self.assertEqual(display_text(reference), "Section 900 BNS (title not shown: trusted sources disagree)")
        self.assertEqual(one("Section 999 IPC", sources).label.state, "conflict")

    def test_the_catalog_outranks_the_mapping(self) -> None:
        # IPC 376 has several CYTRAIN descriptions (a conflict on its own), but the catalog has the section.
        self.assertEqual(len(section_labels.default_sources().mapping[("IPC", "376")]), 9)
        reference = one("Section 376 IPC – rape")
        self.assertEqual((reference.label.state, reference.label.title, reference.label.source), ("verified", "Rape", "section_catalog"))

    def test_mapping_titles_come_from_cytrain_rows_only(self) -> None:
        # BNS 173: CYTRAIN "Punishment for bribery"; the NCRB crime head ("Offences relating to Elections…") is not a title.
        reference = one("Section 173 BNS")
        self.assertEqual((reference.label.state, reference.label.title, reference.label.source),
                         ("verified", "Punishment for bribery", "ipc_bns_mapping"))

    def test_wrong_statute_with_a_trusted_title_in_the_other_statute(self) -> None:
        reference = one("BNSS Sec. 103 (murder).")
        self.assertEqual((reference.statute, reference.section), ("BNS", "103"))
        self.assertEqual((reference.label.state, reference.label.title, reference.label.statute_corrected_from),
                         ("corrected_statute", "Murder", "BNSS"))
        self.assertEqual(display_text(reference), "Section 103 BNS — Murder (statute corrected from BNSS)")

    def test_ipc_named_for_a_crpc_procedure_is_corrected(self) -> None:
        reference = one("IPC Section 482 – Inherent powers of the court to prevent abuse of process")
        self.assertEqual((reference.statute, reference.label.state, reference.label.title),
                         ("CrPC", "corrected_statute", "Inherent powers of High Court"))

    def test_an_agreeing_label_is_verified_without_a_note(self) -> None:
        reference = one("Section 304B IPC – dowry death")
        self.assertEqual((reference.label.state, reference.label.title, reference.label.note), ("verified", "Dowry death", None))


class ParsingTests(Step25Sources):
    def test_model_wordings(self) -> None:
        cases = {
            "IPC Sec. 302 (murder).": ("IPC", "302"),
            "Section 420, Indian Penal Code – cheating": ("IPC", "420"),
            "Section 438 Cr.P.C – Bail for offences punishable with death": ("CrPC", "438"),
            "Section 302 of the Indian Penal Code, 1860 – murder": ("IPC", "302"),
            "NDPS Act, s.21 (commercial quantity offence)": ("NDPS Act", "21"),
            "BNSS section 35": ("BNSS", "35"),
            "Section 3(1)(r) SC/ST Act": ("SC/ST Act", "3(1)(r)"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                reference = one(text)
                self.assertEqual((reference.statute, reference.section), expected)
                self.assertEqual(reference.label.state, "verified")

    def test_section_signs_and_a_statute_first_list(self) -> None:
        # Exactly as the model wrote it in the step 25 live charge-sheet run (it was left unparsed before this rule).
        references = resolve_provision("IPC §§420, 406, 120B – fraud, criminal breach of trust, criminal conspiracy")
        self.assertEqual([(r.statute, r.section, r.label.state) for r in references],
                         [("IPC", "420", "verified"), ("IPC", "406", "verified"), ("IPC", "120B", "verified")])
        self.assertEqual(one("§ 304B IPC – dowry death").label.title, "Dowry death")

    def test_a_label_kept_from_the_model_keeps_its_wording(self) -> None:
        parsed = section_labels.parse_provision("Section 154 Cr.P.C. – registration of FIR (repealed on 01.07.2024).")
        self.assertEqual(parsed.mentions, [("CrPC", "154")])
        self.assertEqual(parsed.label, "registration of FIR (repealed on 01.07.2024)")

    def test_several_sections_in_one_string_get_no_shared_label(self) -> None:
        references = resolve_provision("Sections 302 and 34 IPC – murder with common intention")
        self.assertEqual([(r.section, r.label.title) for r in references], [("302", "Murder"), ("34", "Common intention")])

    def test_hyphenated_ipc_sections_match_the_loaded_mapping(self) -> None:
        self.assertIn(("IPC", "366B"), section_labels.default_sources().mapping)

    def test_duplicates_are_merged(self) -> None:
        references = resolve_provisions(["Section 302 IPC", "IPC Sec. 302 (murder)"])
        self.assertEqual(len(references), 1)


def metadata(mode: AnswerMode) -> ModelGenerationMetadata:
    return ModelGenerationMetadata(provider="mock", configured_model_id="mock-model", response_mode=mode)


def result(mode: AnswerMode, answer) -> LegalAnswerResult:
    return LegalAnswerResult(
        query="query", mode=mode, answer=answer, summary="summary", citations=[],
        grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED, evidence_used=[], evidence_retrieved=[],
        model_metadata=metadata(mode), query_understanding_version="test", retrieval_version="test",
    )


class ResponseMappingTests(Step25Sources):
    def test_professional_sections_and_brief_provisions_use_the_resolver(self) -> None:
        answer = ProfessionalLegalBrief(
            issue_summary="Brief",
            legal_regime="bns_bnss",
            explicit_legal_provisions=list(KNOWN_ERRORS.values()),
            potential_additional_provisions=["Section 113B Evidence Act – presumption"],
        )
        response = query_api.professional_response_from_result(result(AnswerMode.PROFESSIONAL, answer))
        states = [(s.statute, s.section, s.label.state) for s in response.identified_sections]
        self.assertEqual(states, [("BNS", "309(4)", "verified"), ("BNS", "115(2)", "verified"),
                                  ("BNSS", "173", "corrected_statute"), ("Evidence Act", "113B", "unverified")])
        brief = response.case_brief
        self.assertEqual(brief.statutory_provisions[0], "Section 309(4) BNS — Robbery (the answer's own label differs)")
        self.assertEqual(len(brief.statutory_provision_references), 3)  # explicit provisions only
        joined = " ".join(brief.statutory_provisions)
        for wrong in ("suicide", "medical examination"):
            self.assertNotIn(wrong, joined)
        payload = response.model_dump()
        self.assertEqual(payload["identified_sections"][0]["label"]["state"], "verified")

    def test_public_sections_use_the_same_resolver(self) -> None:
        answer = PublicLegalAnswer(summary="Summary", possible_legal_provisions=[KNOWN_ERRORS["robbery"], KNOWN_ERRORS["fir"],
                                                                                 "Section 113B Evidence Act – presumption"])
        response = query_api.public_response_from_result(result(AnswerMode.PUBLIC, answer))
        self.assertEqual([s.title for s in response.sections], [
            "Section 309(4) BNS — Robbery (the answer's own label differs)",
            "Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified label)",
            "Section 113B Evidence Act — presumption (unverified label)",
        ])
        self.assertEqual([s.references[0].label.state for s in response.sections], ["verified", "corrected_statute", "unverified"])


if __name__ == "__main__":
    unittest.main()


def heading(statute: str, section: str, text: str, status: str = "in_force") -> dict:
    return {"statute": statute, "section": section, "heading": text, "status": status}


# Step 26: official headings (India Code marginal notes) as the first trust source. The rows here are test data in the
# CSV shape of data/structured/statute_headings/; the tests do not depend on the committed files.
OFFICIAL = [
    heading("BNS", "309", "Robbery."),
    heading("BNS", "115", "Voluntarily causing hurt."),
    heading("BNS", "173", "Punishment for bribery."),
    heading("BNSS", "173", "Information in cognizable cases."),
    heading("IPC", "120B", "Punishment of criminal conspiracy."),
    heading("IPC", "304B", "Dowry death."),
    heading("IPC", "498A", "Husband or relative of husband of a woman subjecting her to cruelty."),
    heading("IPC", "124A", "", status="omitted"),
    heading("IPC", "377", "Unnatural offences."),
]


class OfficialHeadingTests(unittest.TestCase):
    sources = build_sources(heading_rows=OFFICIAL)
    without = build_sources(heading_rows=[])

    def test_official_heading_is_the_first_source(self) -> None:
        reference = one(KNOWN_ERRORS["robbery"], self.sources)
        self.assertEqual((reference.label.state, reference.label.title, reference.label.source, reference.label.source_key),
                         ("verified", "Robbery", "official_heading", "BNS 309"))
        self.assertNotIn("suicide", display_text(reference))
        # The catalog's title is kept next to it, not dropped.
        self.assertEqual([(o.source, o.title, o.agrees) for o in reference.label.other_sources],
                         [("section_catalog", "Robbery", True)])

    def test_step_25_regressions_hold_with_official_headings(self) -> None:
        hurt = one(KNOWN_ERRORS["hurt"], self.sources)
        self.assertEqual((hurt.statute, hurt.section, hurt.label.state, hurt.label.title),
                         ("BNS", "115(2)", "verified", "Voluntarily causing hurt"))
        fir = one(KNOWN_ERRORS["fir"], self.sources)
        self.assertEqual((fir.statute, fir.section, fir.label.state, fir.label.statute_corrected_from),
                         ("BNSS", "173", "corrected_statute", "BNS"))
        # The corrected section's official heading is shown; the answer's own wording only in the note.
        self.assertEqual((fir.label.title, fir.label.source, fir.label.model_label),
                         ("Information in cognizable cases", "official_heading", "registration of FIR"))
        self.assertEqual(display_text(fir), "Section 173 BNSS — Information in cognizable cases (statute corrected from BNS)")
        self.assertIn("registration of FIR", fir.label.note)

    def test_lettered_sections(self) -> None:
        for text, title in (("Section 120B IPC – conspiracy", "Punishment of criminal conspiracy"),
                            ("Section 304-B IPC", "Dowry death"),
                            ("IPC Sec. 498A – cruelty by husband", "Husband or relative of husband of a woman subjecting her to cruelty")):
            with self.subTest(text=text):
                reference = one(text, self.sources)
                self.assertEqual((reference.label.state, reference.label.title, reference.label.source),
                                 ("verified", title, "official_heading"))

    def test_sub_sections_inherit_the_parent_heading(self) -> None:
        reference = one("Section 309(6) BNS", self.sources)
        self.assertEqual((reference.section, reference.label.title, reference.label.source_key), ("309(6)", "Robbery", "BNS 309"))

    def test_official_heading_wins_a_conflict_with_the_catalog_and_the_disagreement_is_recorded(self) -> None:
        catalog = [{"statute": "IPC", "section": "377", "canonical_name": "Sexual offences against minors",
                    "brief_description": "", "aliases": [], "concepts": []}]
        sources = build_sources(catalog=catalog, mapping_rows=[], heading_rows=OFFICIAL)
        reference = one("Section 377 IPC", sources)
        self.assertEqual((reference.label.title, reference.label.source), ("Unnatural offences", "official_heading"))
        self.assertEqual([(o.source, o.title, o.agrees) for o in reference.label.other_sources],
                         [("section_catalog", "Sexual offences against minors", False)])
        self.assertIn("lower-trust source gives a different title", reference.label.note)

    def test_omitted_sections_are_never_shown_as_titles(self) -> None:
        reference = one("Section 124A IPC – sedition", self.sources)
        self.assertNotEqual(reference.label.source, "official_heading")

    def test_an_act_without_official_headings_falls_back_unchanged(self) -> None:
        # The rows have no CrPC, Evidence Act or NDPS headings: those resolve exactly as without any official data.
        for text in ("Section 438 CrPC – anticipatory bail", "Section 65B Evidence Act – electronic records",
                     "Section 21 NDPS Act – small quantity", "Section 482 IPC – inherent powers"):
            with self.subTest(text=text):
                self.assertEqual(resolve_provision(text, self.sources), resolve_provision(text, self.without))

    def test_no_heading_files_means_no_official_source(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as empty:
            self.assertEqual(section_labels.load_heading_rows(Path(empty)), [])
            self.assertEqual(section_labels.load_heading_rows(Path(empty) / "missing"), [])


class KnownErrorsWithOfficialHeadingsTests(unittest.TestCase):
    """The step 25 regressions against the committed official headings (data/structured/statute_headings/)."""

    def test_bns_309_4_is_robbery(self) -> None:
        reference = one(KNOWN_ERRORS["robbery"])
        self.assertEqual((reference.statute, reference.section, reference.label.state, reference.label.title, reference.label.source),
                         ("BNS", "309(4)", "verified", "Robbery", "official_heading"))
        self.assertNotIn("suicide", display_text(reference))

    def test_bns_115_2_is_voluntarily_causing_hurt(self) -> None:
        reference = one(KNOWN_ERRORS["hurt"])
        self.assertEqual((reference.section, reference.label.state, reference.label.title), ("115(2)", "verified", "Voluntarily causing hurt"))
        self.assertNotIn("medical", display_text(reference))

    def test_173_is_corrected_to_the_bnss(self) -> None:
        reference = one(KNOWN_ERRORS["fir"])
        self.assertEqual((reference.statute, reference.section, reference.label.state, reference.label.statute_corrected_from),
                         ("BNSS", "173", "corrected_statute", "BNS"))
        self.assertNotIn("bribery", display_text(reference).lower())
        self.assertEqual(reference.label.title, "Information in cognizable cases")

    def test_committed_headings_cover_the_lettered_sections(self) -> None:
        for text, title in (("Section 120B IPC", "Punishment of criminal conspiracy"), ("Section 304B IPC", "Dowry death"),
                            ("Section 498A IPC", "Husband or relative of husband of a woman subjecting her to cruelty"),
                            ("Section 65B Evidence Act", "Admissibility of electronic records")):
            with self.subTest(text=text):
                reference = one(text)
                self.assertEqual((reference.label.state, reference.label.title, reference.label.source), ("verified", title, "official_heading"))

    def test_bsa_sections_are_read_by_the_resolver(self) -> None:
        for text, section in (("Section 63 BSA – electronic evidence", "63"), ("BSA Section 23(1)", "23(1)"),
                              ("Section 118 of the Bharatiya Sakshya Adhiniyam, 2023", "118")):
            with self.subTest(text=text):
                reference = one(text)
                self.assertEqual((reference.statute, reference.section, reference.label.source), ("BSA", section, "official_heading"))
        self.assertEqual(one("Section 63 BSA – electronic evidence").label.title, "Admissibility of electronic records")
        self.assertEqual(one("Section 63 BSA").label.title, "Admissibility of electronic records")


class WrongStatuteRuleTests(unittest.TestCase):
    """Step 26b: "clearly does not match" = no shared content word with any trusted entry of the named section."""

    def outcome(self, text: str) -> str:
        label = one(text).label
        if label.state == "corrected_statute":
            return "corrected_statute"
        if label.state == "verified":
            return "flag_differs" if label.model_label_differs else "keep"
        return label.state

    def test_confusion_table_on_the_27_saved_mismatches(self) -> None:
        import collections
        import json

        path = Path(__file__).resolve().parent / "fixtures" / "wrong_statute_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        table = collections.Counter((truth, self.outcome(text)) for text, truth in cases)
        self.assertEqual(len(cases), 27)
        # Every wrong statute is corrected and every wrong label flagged; no label is wrongly corrected. Six correct
        # labels written as synonyms or uses ("challenge to investigation" for BNSS 528) are flagged as differing.
        self.assertEqual(dict(table), {("correct", "keep"): 5, ("correct", "flag_differs"): 6,
                                       ("wrong_statute", "corrected_statute"): 5, ("wrong_label", "flag_differs"): 11})

    def test_bns_173_registration_of_fir_becomes_bnss_173_and_keeps_the_label(self) -> None:
        reference = one("Section 173 BNS – registration of FIR.")
        self.assertEqual((reference.statute, reference.section, reference.label.state, reference.label.title),
                         ("BNSS", "173", "corrected_statute", "Information in cognizable cases"))
        self.assertEqual((reference.label.model_label, reference.label.statute_corrected_from), ("registration of FIR", "BNS"))
        self.assertIn("matches BNSS 173", reference.label.note)

    def test_evidence_act_and_bsa_are_sister_statutes(self) -> None:
        reference = one("Section 63 Evidence Act – admissibility of electronic records")
        self.assertEqual((reference.statute, reference.label.state, reference.label.title),
                         ("BSA", "corrected_statute", "Admissibility of electronic records"))

    def test_no_sister_match_shows_the_official_heading_with_the_flag(self) -> None:
        reference = one("Section 138 IPC – Dishonour of cheque")
        self.assertEqual((reference.statute, reference.label.state, reference.label.model_label_differs, reference.label.model_label),
                         ("IPC", "verified", True, "Dishonour of cheque"))
        self.assertEqual(reference.label.title, "Abetment of act of insubordination by soldier, sailor or airman")
        self.assertNotIn("cheque", display_text(reference).split("(")[0])

    def test_a_matching_label_is_kept_without_a_flag(self) -> None:
        reference = one("Section 302 IPC – punishment for murder")
        self.assertEqual((reference.label.state, reference.label.model_label_differs, reference.label.model_label),
                         ("verified", False, "punishment for murder"))


class SubSectionTitleTests(unittest.TestCase):
    """Step 26b: a catalog title for the exact sub-section is primary, the official section heading alongside."""

    def test_bns_3_5_common_intention(self) -> None:
        label = one("Section 3(5) BNS").label
        self.assertEqual((label.title, label.source, label.source_key), ("Common intention", "section_catalog", "BNS 3(5)"))
        self.assertEqual((label.section_heading, label.section_heading_source, label.section_heading_key),
                         ("General explanations", "official_heading", "BNS 3"))
        self.assertEqual(display_text(one("Section 3(5) BNS")),
                         "Section 3(5) BNS — Common intention (sub-section, catalog); General explanations (section heading, official)")

    def test_bnss_173_4(self) -> None:
        label = one("Section 173(4) BNSS").label
        self.assertEqual((label.title, label.section_heading), ("Information to Superintendent of Police", "Information in cognizable cases"))

    def test_without_a_sub_section_title_the_official_heading_stays_primary(self) -> None:
        label = one("Section 309(4) BNS").label
        self.assertEqual((label.title, label.source, label.section_heading), ("Robbery", "official_heading", None))
