"""Step 25: section labels in answers and briefs are resolved against the trusted sources (services/section_labels.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


def one(text: str, sources=None):
    references = resolve_provision(text, sources)
    assert len(references) == 1, references
    return references[0]


class KnownErrorRegressionTests(unittest.TestCase):
    def test_bns_309_4_is_robbery_not_suicide(self) -> None:
        reference = one(KNOWN_ERRORS["robbery"])
        self.assertEqual((reference.statute, reference.section), ("BNS", "309(4)"))
        self.assertEqual((reference.label.state, reference.label.title, reference.label.source),
                         ("verified", "Robbery", "section_catalog"))
        self.assertEqual(reference.label.source_key, "BNS 309")
        self.assertIsNone(reference.label.model_label)
        self.assertIn("did not match", reference.label.note)
        self.assertEqual(display_text(reference), "Section 309(4) BNS — Robbery")
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


class StateTests(unittest.TestCase):
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


class ParsingTests(unittest.TestCase):
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


class ResponseMappingTests(unittest.TestCase):
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
        self.assertEqual(brief.statutory_provisions[0], "Section 309(4) BNS — Robbery")
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
            "Section 309(4) BNS — Robbery",
            "Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified label)",
            "Section 113B Evidence Act — presumption (unverified label)",
        ])
        self.assertEqual([s.references[0].label.state for s in response.sections], ["verified", "corrected_statute", "unverified"])


if __name__ == "__main__":
    unittest.main()
