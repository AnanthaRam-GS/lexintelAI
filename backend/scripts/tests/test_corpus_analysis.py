"""Tests for deterministic corpus analysis filters."""

from __future__ import annotations

import unittest

from backend.scripts.corpus_analysis.criminal_relevance import assess_criminal_relevance
from backend.scripts.corpus_analysis.document_type import assess_document_type
from backend.scripts.corpus_analysis.metadata_quality import assess_metadata_quality
from backend.scripts.corpus_analysis.regime_detector import detect_legal_regime
from backend.scripts.corpus_analysis.scoring import decide_candidate_quality, quota_allows
from backend.scripts.corpus_analysis.statute_detector import detect_statutes


COMPLETE_RECORD = {
    "source_document_id": "1",
    "source_url": "https://indiankanoon.org/doc/1/",
    "case_name": "A v State",
    "court_name": "Example High Court",
    "court_level": "high_court",
    "year": 2024,
    "raw_file_path": "data/raw/example.pdf",
    "sha256": "a" * 64,
    "file_size_bytes": 100,
    "mime_type": "application/pdf",
    "attribution_required": True,
    "offence_family": "theft_and_robbery",
}
CRIMINAL_JUDGMENT = """
HIGH COURT OF EXAMPLE
Criminal Appeal No. 10 of 2024
A v State
Hon'ble Justice Example delivered the judgment. The accused was convicted
under Section 302 IPC after investigation, FIR, charge sheet, prosecution
evidence, conviction and sentence.
"""


class CorpusAnalysisTest(unittest.TestCase):
    def test_document_type_obvious_rules_report_downgraded(self) -> None:
        result = assess_document_type("Law Commission Report Vol(1) Rules Circular Gazette")
        self.assertFalse(result.likely_judgment)
        self.assertIn("law_commission_report", result.negative_signals)

    def test_document_type_judgment_like_document_passes(self) -> None:
        result = assess_document_type(CRIMINAL_JUDGMENT)
        self.assertTrue(result.likely_judgment)
        self.assertGreaterEqual(result.score, 0.6)

    def test_criminal_relevance_strong_ipc_text(self) -> None:
        result = assess_criminal_relevance(CRIMINAL_JUDGMENT)
        self.assertGreaterEqual(result.score, 0.7)
        self.assertTrue(result.is_criminal_candidate)

    def test_criminal_relevance_strong_bns_text(self) -> None:
        result = assess_criminal_relevance(
            "Criminal appeal by accused under BNS Section 103 after FIR and conviction."
        )
        self.assertGreaterEqual(result.score, 0.4)
        self.assertTrue(result.is_criminal_candidate)

    def test_criminal_relevance_mixed_civil_terms_uncertain(self) -> None:
        result = assess_criminal_relevance(
            "Criminal complaint alleging IPC Section 420 in a property dispute civil suit."
        )
        self.assertGreaterEqual(result.score, 0.4)
        self.assertLess(result.score, 0.7)

    def test_criminal_relevance_non_criminal_low(self) -> None:
        result = assess_criminal_relevance("Income tax GST service matter company law.")
        self.assertLess(result.score, 0.4)

    def test_statute_detection_common_forms(self) -> None:
        texts = [
            ("IPC 302", "IPC", "302"),
            ("Section 302 IPC", "IPC", "302"),
            ("Section 302 of the Indian Penal Code", "IPC", "302"),
            ("BNS Section 103", "BNS", "103"),
            ("Section 103 of Bharatiya Nyaya Sanhita", "BNS", "103"),
            ("Code of Criminal Procedure CrPC", "CrPC", None),
            ("Bharatiya Nagarik Suraksha Sanhita BNSS", "BNSS", None),
        ]
        for text, statute, section in texts:
            result = detect_statutes(text)
            self.assertIn(statute, result.detected_statutes)
            if section:
                self.assertTrue(
                    any(item.statute == statute and item.section == section for item in result.detected_sections)
                )

    def test_regime_detection_uses_statute_evidence_not_year(self) -> None:
        self.assertEqual(detect_legal_regime("Section 302 IPC and CrPC").regime, "ipc_crpc")
        self.assertEqual(detect_legal_regime("BNS Section 103 and BNSS").regime, "bns_bnss")
        self.assertEqual(detect_legal_regime("IPC and Bharatiya Nyaya Sanhita").regime, "mixed_or_transition")
        self.assertEqual(detect_legal_regime("Judgment dated 2026 without statute").regime, "unknown")

    def test_metadata_quality_complete_provenance_high_score(self) -> None:
        result = assess_metadata_quality(COMPLETE_RECORD)
        self.assertGreaterEqual(result.score, 0.9)

    def test_metadata_quality_missing_source_url_sha_penalized(self) -> None:
        record = dict(COMPLETE_RECORD)
        record["source_url"] = None
        record["sha256"] = None
        result = assess_metadata_quality(record)
        self.assertLess(result.score, 0.8)
        self.assertIn("source_url", result.missing_fields)
        self.assertIn("sha256", result.missing_fields)

    def test_combined_decision_duplicate_rejected(self) -> None:
        result = decide_candidate_quality(CRIMINAL_JUDGMENT, COMPLETE_RECORD, duplicate=True)
        self.assertEqual(result.decision, "reject")
        self.assertIn("duplicate_candidate", result.reasons)

    def test_combined_decision_corrupt_content_rejected(self) -> None:
        result = decide_candidate_quality(CRIMINAL_JUDGMENT, COMPLETE_RECORD, corrupt=True)
        self.assertEqual(result.decision, "reject")

    def test_combined_decision_strong_criminal_judgment_accepted_candidate(self) -> None:
        result = decide_candidate_quality(CRIMINAL_JUDGMENT, COMPLETE_RECORD)
        self.assertEqual(result.decision, "accept_candidate")

    def test_combined_decision_uncertain_needs_review(self) -> None:
        text = "A v State. Hon'ble Court order in criminal complaint mentioning IPC Section 420 and civil suit."
        result = decide_candidate_quality(text, COMPLETE_RECORD)
        self.assertEqual(result.decision, "needs_review")

    def test_quota_enforcement(self) -> None:
        quotas = {"homicide": 1, "theft_and_robbery": 1}
        self.assertFalse(quota_allows("homicide", {"homicide": 1}, quotas))
        self.assertTrue(quota_allows("theft_and_robbery", {"homicide": 1}, quotas))
        result = decide_candidate_quality(
            CRIMINAL_JUDGMENT,
            COMPLETE_RECORD,
            accepted_counts={"theft_and_robbery": 1},
            quotas=quotas,
        )
        self.assertEqual(result.decision, "needs_review")
        self.assertIn("offence_family_quota_reached", result.reasons)

    def test_poor_candidate_not_accepted_to_fill_quota(self) -> None:
        result = decide_candidate_quality(
            "Income tax service matter.",
            COMPLETE_RECORD,
            accepted_counts={"theft_and_robbery": 0},
            quotas={"theft_and_robbery": 5},
        )
        self.assertEqual(result.decision, "reject")


if __name__ == "__main__":
    unittest.main()
