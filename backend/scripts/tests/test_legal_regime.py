import unittest

from backend.app.services.legal_regime import regime_match_class, resolve_legal_regime


class LegalRegimeResolverTests(unittest.TestCase):
    def test_explicit_crpc_resolves_old_regime(self) -> None:
        resolved = resolve_legal_regime("anticipatory bail under Section 438 CrPC")
        self.assertEqual(resolved.regime, "ipc_crpc")
        self.assertEqual(resolved.confidence, "high")
        self.assertIn("CrPC", resolved.explicit_codes)
        self.assertIn("Section 438", resolved.explicit_sections)

    def test_explicit_bns_resolves_new_regime(self) -> None:
        resolved = resolve_legal_regime("offence under BNS after 1 July 2024")
        self.assertEqual(resolved.regime, "bns_bnss")
        self.assertEqual(resolved.confidence, "high")
        self.assertIn("BNS", resolved.explicit_codes)

    def test_mixed_old_and_new_codes_resolve_transition(self) -> None:
        resolved = resolve_legal_regime("IPC offence with bail application under BNSS")
        self.assertEqual(resolved.regime, "mixed_or_transition")
        self.assertEqual(resolved.confidence, "high")
        self.assertEqual(set(resolved.explicit_codes), {"IPC", "BNSS"})

    def test_date_only_query_stays_unknown(self) -> None:
        resolved = resolve_legal_regime("case registered in 2023 but heard in 2025")
        self.assertEqual(resolved.regime, "unknown")
        self.assertEqual(resolved.confidence, "low")
        self.assertEqual(resolved.explicit_codes, [])

    def test_bare_section_number_is_not_mapped(self) -> None:
        resolved = resolve_legal_regime("section 482 quashing petition")
        self.assertEqual(resolved.regime, "unknown")
        self.assertEqual(resolved.confidence, "low")
        self.assertEqual(resolved.explicit_codes, [])
        self.assertIn("section 482", resolved.explicit_sections)

    def test_unknown_query_stays_unknown(self) -> None:
        resolved = resolve_legal_regime("criminal appeal involving assault")
        self.assertEqual(resolved.regime, "unknown")
        self.assertEqual(resolved.confidence, "low")

    def test_regime_match_classes(self) -> None:
        self.assertEqual(regime_match_class("bns_bnss", "bns_bnss"), "exact_regime_match")
        self.assertEqual(regime_match_class("mixed_or_transition", "ipc_crpc"), "transition_compatible")
        self.assertEqual(regime_match_class("ipc_crpc", None), "unknown_metadata")
        self.assertEqual(regime_match_class("bns_bnss", "ipc_crpc"), "regime_mismatch")


if __name__ == "__main__":
    unittest.main()
