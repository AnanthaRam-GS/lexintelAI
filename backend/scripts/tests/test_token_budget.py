import unittest

from backend.app.core.config import Settings
from backend.app.services.token_budget import TokenBudget, estimate_tokens, resolve_token_budget


class TokenEstimatorTests(unittest.TestCase):
    def test_empty_text_estimates_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_estimate_is_deterministic(self) -> None:
        text = "The accused was granted bail under Section 302 IPC subject to conditions."
        self.assertEqual(estimate_tokens(text), estimate_tokens(text))

    def test_estimate_scales_with_length(self) -> None:
        short = "Bail granted."
        long = "Bail granted. " * 50
        self.assertLess(estimate_tokens(short), estimate_tokens(long))

    def test_estimate_biases_toward_overestimation_via_structural_multiplier(self) -> None:
        # The structural-overhead multiplier must make our estimate at least as
        # large as the raw underlying word-count-based estimator it wraps.
        from backend.scripts.process_judgment_corpus import estimated_tokens

        text = "Section 302 IPC murder bail application before the Sessions Court."
        self.assertGreaterEqual(estimate_tokens(text), estimated_tokens(text))


class TokenBudgetTests(unittest.TestCase):
    def budget(self, **overrides) -> TokenBudget:
        defaults = dict(
            context_tokens=10000,
            reserved_output_tokens=2000,
            safety_margin_tokens=1000,
            private_pdf_ceiling_tokens=4000,
            trusted_evidence_ceiling_tokens=3000,
        )
        defaults.update(overrides)
        return TokenBudget(**defaults)

    def test_available_input_tokens_subtracts_output_and_margin(self) -> None:
        budget = self.budget()
        self.assertEqual(budget.available_input_tokens, 10000 - 2000 - 1000)

    def test_available_input_tokens_never_negative(self) -> None:
        budget = self.budget(context_tokens=100, reserved_output_tokens=2000, safety_margin_tokens=1000)
        self.assertEqual(budget.available_input_tokens, 0)

    def test_private_pdf_budget_uses_measured_usage_not_a_static_guess(self) -> None:
        budget = self.budget()  # available_input_tokens = 7000
        # A small already-used amount leaves most of the ceiling available.
        self.assertEqual(budget.private_pdf_budget(already_used_tokens=1000), 4000)
        # A large already-used amount (e.g. a big trusted-evidence prompt)
        # leaves less than the ceiling, and the private budget shrinks with it.
        self.assertEqual(budget.private_pdf_budget(already_used_tokens=6000), 1000)

    def test_private_pdf_budget_is_zero_when_nothing_remains(self) -> None:
        budget = self.budget()
        self.assertEqual(budget.private_pdf_budget(already_used_tokens=999999), 0)

    def test_private_pdf_budget_never_exceeds_configured_ceiling(self) -> None:
        budget = self.budget(private_pdf_ceiling_tokens=500)
        self.assertEqual(budget.private_pdf_budget(already_used_tokens=0), 500)

    def test_resolve_token_budget_reads_from_settings(self) -> None:
        settings = Settings(
            legalai_product_max_input_tokens=9999,
            legalai_llm_reserved_output_tokens=111,
            legalai_llm_context_safety_margin_tokens=222,
            private_pdf_input_budget_tokens=333,
            trusted_evidence_input_budget_tokens=444,
        )
        budget = resolve_token_budget(settings)
        self.assertEqual(budget.context_tokens, 9999)
        self.assertEqual(budget.reserved_output_tokens, 111)
        self.assertEqual(budget.safety_margin_tokens, 222)
        self.assertEqual(budget.private_pdf_ceiling_tokens, 333)
        self.assertEqual(budget.trusted_evidence_ceiling_tokens, 444)


if __name__ == "__main__":
    unittest.main()
