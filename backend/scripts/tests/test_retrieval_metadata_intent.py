import unittest

from backend.app.services.retrieval_metadata_intent import metadata_features, parse_metadata_intent


class RetrievalMetadataIntentTests(unittest.TestCase):
    def test_supreme_court_recognition(self) -> None:
        intent = parse_metadata_intent("Supreme Court criminal appeal discussing murder conviction")
        self.assertEqual(intent.court_level, "supreme_court")
        self.assertEqual(intent.posture, "criminal_appeal")
        self.assertEqual(intent.offence_family, "homicide")

    def test_high_court_recognition(self) -> None:
        intent = parse_metadata_intent("High Court petition seeking FIR quashing in commercial dispute")
        self.assertEqual(intent.court_level, "high_court")
        self.assertEqual(intent.posture, "quashing_petition")
        self.assertEqual(intent.offence_family, "cheating_and_fraud")

    def test_trial_and_date_recognition(self) -> None:
        intent = parse_metadata_intent("trial court conviction appeal after July 2024")
        self.assertEqual(intent.court_level, "district_court")
        self.assertEqual(intent.date_relation, "after")
        self.assertEqual(intent.date_value, "2024-07-01")

    def test_regime_intent_reuses_resolver(self) -> None:
        intent = parse_metadata_intent("BNSS bail for an IPC offence registered before July 2024")
        self.assertEqual(intent.legal_regime, "mixed_or_transition")

    def test_unknown_metadata_is_neutral(self) -> None:
        intent = parse_metadata_intent("Supreme Court criminal appeal")
        features = metadata_features(intent, {"court": {}, "decision_date": "", "case_title": ""})
        self.assertEqual(features["court_match"], "neutral")
        self.assertEqual(features["court_level_match"], "neutral")

    def test_mismatch_safety(self) -> None:
        intent = parse_metadata_intent("Supreme Court criminal appeal")
        features = metadata_features(intent, {"court": {"court_name": "Delhi High Court", "court_level": "high_court"}, "case_title": "Bail Petition"})
        self.assertEqual(features["court_level_match"], "mismatch")
        self.assertEqual(features["posture_match"], "mismatch")


if __name__ == "__main__":
    unittest.main()
