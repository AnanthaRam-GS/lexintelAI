"""Unit tests for the conservative operative-part outcome rules."""

from __future__ import annotations

import unittest

from backend.app.services.judgment_outcomes import OPERATIVE_CHUNKS, extract_outcomes, operative_chunks


def outcomes(text: str) -> dict:
    return extract_outcomes([("doc:chunk:0009", text)])


class OutcomeRuleTests(unittest.TestCase):
    def assertFound(self, text: str, field: str, value: str, rule: str) -> None:
        finding = outcomes(text)[field]
        self.assertEqual((finding.status, finding.value, finding.rule, finding.chunk_id), ("found", value, rule, "doc:chunk:0009"))

    def assertStatus(self, text: str, field: str, status: str) -> None:
        finding = outcomes(text)[field]
        self.assertEqual(finding.status, status)
        self.assertIsNone(finding.value)

    # positive
    def test_appeal_dismissed(self) -> None:
        self.assertFound("In the result, the appeal is dismissed.", "appeal_result", "dismissed", "appeal_dismissed")
        self.assertFound("In the result, the appeal is dismissed.", "case_disposition", "appeal dismissed", "disposition_appeal_dismissed")

    def test_appeal_allowed_and_acquittal(self) -> None:
        text = "The appeal is allowed. The impugned judgment is set aside and the appellants are acquitted of all charges."
        self.assertFound(text, "appeal_result", "allowed", "appeal_allowed")
        self.assertFound(text, "conviction_status", "acquitted", "accused_acquitted")
        self.assertFound(text, "case_disposition", "appeal allowed", "disposition_appeal_allowed")

    def test_partly_allowed_variants(self) -> None:
        for text in ("The criminal revision is partly allowed.", "Criminal Appeal No. 160 of 2017 is allowed in part."):
            with self.subTest(text=text):
                self.assertFound(text, "appeal_result", "partly allowed", "appeal_partly_allowed")

    def test_conviction_upheld(self) -> None:
        self.assertFound("The conviction of the appellant under Section 302 IPC is upheld.", "conviction_status", "convicted", "conviction_upheld")
        self.assertFound("We, therefore, affirm the conviction recorded by the trial court.", "conviction_status", "convicted", "conviction_upheld")

    def test_bail_granted_supersedes_petition_allowed(self) -> None:
        self.assertFound("The application for anticipatory bail is allowed.", "case_disposition", "bail granted", "bail_granted")

    def test_proceedings_quashed(self) -> None:
        self.assertFound("The criminal proceedings are hereby quashed and set aside.", "case_disposition", "proceedings quashed", "proceedings_quashed")

    def test_remanded(self) -> None:
        self.assertFound("The matter is remanded to the trial court for fresh consideration.", "case_disposition", "remanded", "matter_remanded")

    # negative: narrated history, argument, conditional phrasing
    def test_past_tense_history_does_not_fire(self) -> None:
        text = "The appeal was dismissed by the High Court and the accused was convicted under Section 302 IPC."
        for field in ("appeal_result", "conviction_status", "case_disposition"):
            with self.subTest(field=field):
                self.assertStatus(text, field, "unknown")

    def test_argument_about_acquittal_does_not_fire(self) -> None:
        self.assertStatus("The reasons for acquittal of the accused are manifestly erroneous.", "conviction_status", "unknown")

    def test_conditional_phrasing_does_not_fire(self) -> None:
        self.assertStatus("The appeals are liable to be partly allowed on the question of sentence", "appeal_result", "unknown")

    def test_custody_remand_does_not_fire(self) -> None:
        self.assertStatus("despite taking police custody remand of the accused", "case_disposition", "unknown")

    def test_negated_outcome_does_not_fire(self) -> None:
        self.assertStatus("We are not inclined to hold that the appeal is not maintainable.", "appeal_result", "unknown")

    # ambiguous: conflicting results return no value
    def test_present_tense_narration_of_trial_conviction_does_not_fire(self) -> None:
        # Spot check: a revision narrating the trial court's conviction.
        self.assertStatus(
            "This is the case of theft and petitioner is convicted for the offence under Section 379 of IPC.",
            "conviction_status",
            "unknown",
        )

    def test_hypothetical_clause_does_not_fire(self) -> None:
        # Spot check: "what if the appellant is acquitted" is not an acquittal.
        self.assertStatus("The two contrary assumptions are: first, what if the appellant is acquitted", "conviction_status", "unknown")
        self.assertStatus("In the event the appeal is allowed, the fine shall be refunded", "appeal_result", "unknown")

    def test_modal_separate_opinion_does_not_fire(self) -> None:
        # Spot check: a separate opinion saying what the judge "would" do.
        self.assertStatus("On the contrary, I would maintain the convictions and sentences of the appellants", "conviction_status", "unknown")

    def test_conviction_narration_alongside_acquittal_is_ambiguous(self) -> None:
        result = outcomes("Accused No. 1 is acquitted. Accused No. 2 is convicted under Section 307 IPC.")
        self.assertEqual((result["conviction_status"].status, result["conviction_status"].value), ("ambiguous", None))
        # Spot check: one acquitted co-accused does not make the case an acquittal.
        self.assertEqual((result["case_disposition"].status, result["case_disposition"].value), ("ambiguous", None))

    def test_acquittal_disposition_when_conviction_status_agrees(self) -> None:
        self.assertFound("The appellants are acquitted of the charges.", "case_disposition", "acquitted", "disposition_acquitted")

    def test_co_accused_with_different_results_is_ambiguous(self) -> None:
        text = "Accused No. 1 is acquitted. The conviction of Accused No. 2 under Section 304 Part II IPC is upheld."
        finding = outcomes(text)["conviction_status"]
        self.assertEqual((finding.status, finding.value), ("ambiguous", None))
        self.assertEqual(finding.candidates, ("acquitted", "convicted"))

    def test_cross_appeals_with_different_results_are_ambiguous(self) -> None:
        text = "The appeal filed by the State is dismissed. The appeal filed by the accused is allowed."
        self.assertStatus(text, "appeal_result", "ambiguous")
        self.assertStatus(text, "case_disposition", "ambiguous")

    def test_no_operative_text_is_unknown(self) -> None:
        for field, finding in outcomes("List the matter after two weeks.").items():
            with self.subTest(field=field):
                self.assertEqual((finding.status, finding.value), ("unknown", None))

    def test_only_concluding_chunks_are_read(self) -> None:
        chunks = [(0, "c0", "The appeal is dismissed."), (1, "c1", "Facts."), (2, "c2", "Analysis."), (3, "c3", "List later.")]
        selected = operative_chunks(chunks)
        self.assertEqual([chunk_id for chunk_id, _ in selected], ["c2", "c3"][-OPERATIVE_CHUNKS:])
        self.assertEqual(extract_outcomes(selected)["appeal_result"].status, "unknown")


if __name__ == "__main__":
    unittest.main()
