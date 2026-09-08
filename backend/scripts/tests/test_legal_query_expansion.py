import unittest

from backend.app.services.legal_query_expansion import MAX_EXPANSION_TERMS, expanded_query_text, expand_legal_query


class LegalQueryExpansionTests(unittest.TestCase):
    def test_statute_aliases_are_explicit_only(self) -> None:
        expansion = expand_legal_query("Section 438 CrPC anticipatory bail")
        self.assertIn("Code of Criminal Procedure", expansion.expanded_terms)
        self.assertIn("pre-arrest bail", expansion.expanded_terms)
        self.assertIn("explicit_section_retained_without_cross_statute_mapping", expansion.warnings)

    def test_plain_entrustment_mapping(self) -> None:
        expansion = expand_legal_query("money was entrusted but he kept it")
        self.assertIn("criminal breach of trust", expansion.expanded_terms)
        self.assertIn("entrustment", expansion.expanded_terms)
        self.assertIn("misappropriation", expansion.expanded_terms)

    def test_robbery_force_mapping_preserves_discriminator(self) -> None:
        expansion = expand_legal_query("property taken after threatening victim")
        self.assertIn("robbery", expansion.expanded_terms)
        self.assertIn("theft", expansion.expanded_terms)
        self.assertIn("fear", expansion.expanded_terms)
        self.assertTrue(any(group.discriminator for group in expansion.expansion_groups))

    def test_breach_of_contract_not_automatically_cheating(self) -> None:
        expansion = expand_legal_query("breach of contract")
        self.assertNotIn("cheating", expansion.expanded_terms)
        self.assertIn("breach_of_contract_not_expanded_to_cheating_without_fraud_language", expansion.warnings)

    def test_breach_of_contract_with_cheating_context_gets_disambiguators(self) -> None:
        expansion = expand_legal_query("breach of contract allegation wrongly framed as cheating")
        self.assertIn("dishonest intention at inception", expansion.expanded_terms)
        self.assertIn("civil dispute", expansion.expanded_terms)

    def test_budget_and_deterministic_ordering(self) -> None:
        query = "BNSS CrPC IPC BNS property taken by force false promise entrusted money lawful custody marriage demands"
        first = expand_legal_query(query)
        second = expand_legal_query(query)
        self.assertEqual(first.expanded_terms, second.expanded_terms)
        self.assertLessEqual(len(first.expanded_terms), MAX_EXPANSION_TERMS)

    def test_weighted_variant_preserves_original_query(self) -> None:
        query = "investors induced to part with money by false promise"
        expanded = expanded_query_text(query, "Q2")
        self.assertTrue(expanded.startswith(f"{query} {query}"))
        self.assertIn("dishonest inducement", expanded)


if __name__ == "__main__":
    unittest.main()
