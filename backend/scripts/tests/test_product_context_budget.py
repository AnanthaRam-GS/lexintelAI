"""Tests for product-wide trusted-evidence context budgeting.

No live provider calls anywhere in this file.
"""

from __future__ import annotations

import unittest

from backend.app.core.config import Settings
from backend.app.services.legal_citation_validation import validate_legal_answer_citations
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    ClaimType,
    GroundedCitation,
    GroundedLegalClaim,
    GroundingStatus,
    LegalAnswerResult,
    ModelGenerationMetadata,
)
from backend.app.services.product_context_budget import (
    ContextTier,
    ProductContextBudget,
    bound_trusted_evidence,
    evidence_metrics,
    excerpt_at_boundary,
    resolve_product_context_budget,
)
from backend.app.services.token_budget import estimate_tokens
from backend.scripts.tests.test_legal_answer_foundation import evidence, retrieval


def word_text(word_count: int, prefix: str = "fact") -> str:
    return " ".join(f"{prefix}{i}" for i in range(word_count))


class ProductContextBudgetTests(unittest.TestCase):
    def budget(self, **overrides) -> ProductContextBudget:
        defaults = dict(
            max_input_tokens=10000,
            reserved_output_tokens=2000,
            safety_margin_tokens=1000,
            prompt_overhead_reserve_tokens=1000,
            trusted_evidence_ceiling_tokens=5000,
        )
        defaults.update(overrides)
        return ProductContextBudget(**defaults)

    def test_available_input_tokens_subtracts_all_reserves(self) -> None:
        budget = self.budget()
        self.assertEqual(budget.available_input_tokens, 10000 - 2000 - 1000 - 1000)

    def test_trusted_evidence_budget_capped_by_ceiling(self) -> None:
        budget = self.budget(trusted_evidence_ceiling_tokens=500)
        self.assertEqual(budget.trusted_evidence_budget(query_tokens=0), 500)

    def test_trusted_evidence_budget_capped_by_remaining_room(self) -> None:
        budget = self.budget()  # available = 6000
        self.assertEqual(budget.trusted_evidence_budget(query_tokens=5900), 100)

    def test_trusted_evidence_budget_never_negative(self) -> None:
        budget = self.budget()
        self.assertEqual(budget.trusted_evidence_budget(query_tokens=999999), 0)

    def test_reduced_tier_halves_evidence_ceiling_only(self) -> None:
        budget = self.budget(trusted_evidence_ceiling_tokens=4000)
        reduced = budget.reduced()
        self.assertEqual(reduced.trusted_evidence_ceiling_tokens, 2000)
        self.assertEqual(reduced.max_input_tokens, budget.max_input_tokens)
        self.assertEqual(reduced.reserved_output_tokens, budget.reserved_output_tokens)

    def test_resolve_from_settings(self) -> None:
        settings = Settings(
            legalai_product_max_input_tokens=7777,
            legalai_llm_reserved_output_tokens=111,
            legalai_llm_context_safety_margin_tokens=222,
            prompt_overhead_reserve_tokens=333,
            trusted_evidence_input_budget_tokens=444,
        )
        budget = resolve_product_context_budget(settings)
        self.assertEqual(budget.max_input_tokens, 7777)
        self.assertEqual(budget.reserved_output_tokens, 111)
        self.assertEqual(budget.safety_margin_tokens, 222)
        self.assertEqual(budget.prompt_overhead_reserve_tokens, 333)
        self.assertEqual(budget.trusted_evidence_ceiling_tokens, 444)


class ExcerptAtBoundaryTests(unittest.TestCase):
    def test_text_within_budget_is_returned_unchanged(self) -> None:
        text = "Short legal statement."
        self.assertEqual(excerpt_at_boundary(text, 1000), text)

    def test_zero_budget_returns_empty(self) -> None:
        self.assertEqual(excerpt_at_boundary("some text", 0), "")

    def test_prefers_paragraph_boundary_over_character_cutoff(self) -> None:
        text = "\n\n".join([word_text(20, "p1w"), word_text(20, "p2w"), word_text(20, "p3w")])
        excerpt = excerpt_at_boundary(text, estimate_tokens(word_text(20, "p1w")) + 2)
        self.assertTrue(excerpt.startswith("p1w0"))
        self.assertNotIn("p2w0", excerpt)
        # A full paragraph was kept, not a mid-word slice.
        self.assertTrue(excerpt.endswith("p1w19") or "p1w19" in excerpt)

    def test_falls_back_to_sentence_boundary_within_one_paragraph(self) -> None:
        text = "First sentence here. Second sentence here. Third sentence here."
        excerpt = excerpt_at_boundary(text, estimate_tokens("First sentence here.") + 1)
        self.assertIn("First sentence here.", excerpt)
        self.assertNotIn("Third sentence here.", excerpt)

    def test_falls_back_to_character_cutoff_only_when_no_boundary_fits(self) -> None:
        # Space-separated words (so the word-count estimator sees real size)
        # but no paragraph or sentence boundary anywhere in the text.
        text = " ".join(["word"] * 500)
        excerpt = excerpt_at_boundary(text, 5)
        self.assertLess(estimate_tokens(excerpt), estimate_tokens(text))
        self.assertGreater(len(excerpt), 0)


class BoundTrustedEvidenceTests(unittest.TestCase):
    def make_retrieval(self, sizes: list[int]):
        items = [evidence(f"E{i + 1}", text=word_text(size, f"e{i + 1}w")) for i, size in enumerate(sizes)]
        return retrieval(items)

    def test_all_evidence_retained_when_budget_is_generous(self) -> None:
        r = self.make_retrieval([50, 50, 50, 50, 50])
        bounded = bound_trusted_evidence(r, budget_tokens=100000)
        self.assertEqual([item.citation_id for item in bounded.evidence], ["E1", "E2", "E3", "E4", "E5"])

    def test_only_leading_evidence_retained_under_tight_budget(self) -> None:
        r = self.make_retrieval([200, 200, 200, 200, 200])
        one_item_tokens = estimate_tokens(word_text(200, "e1w"))
        bounded = bound_trusted_evidence(r, budget_tokens=one_item_tokens * 3)
        ids = [item.citation_id for item in bounded.evidence]
        self.assertEqual(ids, ["E1", "E2", "E3"])

    def test_never_drops_a_higher_ranked_item_to_include_a_lower_ranked_one(self) -> None:
        # E1 is oversized; a naive strategy might skip it and include smaller
        # E2/E3 instead. The correct behavior stops at E1 (excerpted) and
        # never reaches E2/E3, preserving rank order strictly.
        r = self.make_retrieval([1000, 10, 10])
        e1_tokens = estimate_tokens(word_text(1000, "e1w"))
        budget = e1_tokens // 4  # enough for a meaningful E1 excerpt, not all of E1
        bounded = bound_trusted_evidence(r, budget_tokens=budget)
        ids = [item.citation_id for item in bounded.evidence]
        self.assertEqual(ids, ["E1"])

    def test_very_small_budget_prioritizes_highest_ranked_evidence(self) -> None:
        r = self.make_retrieval([200, 200, 200])
        small_budget = estimate_tokens(word_text(200, "e1w")) // 2
        bounded = bound_trusted_evidence(r, budget_tokens=small_budget)
        ids = [item.citation_id for item in bounded.evidence]
        self.assertIn("E1", ids)
        self.assertNotIn("E3", ids)

    def test_oversized_individual_evidence_is_excerpted_not_dropped(self) -> None:
        r = self.make_retrieval([1000])
        e1_tokens = estimate_tokens(word_text(1000, "e1w"))
        bounded = bound_trusted_evidence(r, budget_tokens=e1_tokens // 4)
        self.assertEqual(len(bounded.evidence), 1)
        self.assertEqual(bounded.evidence[0].citation_id, "E1")
        self.assertLess(len(bounded.evidence[0].text), len(r.evidence[0].text))
        self.assertGreater(len(bounded.evidence[0].text), 0)

    def test_zero_budget_retains_nothing(self) -> None:
        r = self.make_retrieval([50, 50])
        bounded = bound_trusted_evidence(r, budget_tokens=0)
        self.assertEqual(bounded.evidence, [])

    def test_deterministic_across_repeated_calls(self) -> None:
        r = self.make_retrieval([100, 100, 100])
        budget = estimate_tokens(word_text(100, "e1w"))
        first = bound_trusted_evidence(r, budget_tokens=budget)
        second = bound_trusted_evidence(r, budget_tokens=budget)
        self.assertEqual([i.citation_id for i in first.evidence], [i.citation_id for i in second.evidence])

    def test_source_metadata_preserved_on_included_and_excerpted_items(self) -> None:
        r = self.make_retrieval([50, 1000])
        e1_tokens = estimate_tokens(word_text(50, "e1w"))
        e2_tokens = estimate_tokens(word_text(1000, "e2w"))
        bounded = bound_trusted_evidence(r, budget_tokens=e1_tokens + e2_tokens // 4)
        for original, bounded_item in zip(r.evidence, bounded.evidence):
            self.assertEqual(original.citation_id, bounded_item.citation_id)
            self.assertEqual(original.case_name, bounded_item.case_name)
            self.assertEqual(original.source_url, bounded_item.source_url)
            self.assertEqual(original.paragraph_start, bounded_item.paragraph_start)

    def test_original_retrieval_object_is_not_mutated(self) -> None:
        r = self.make_retrieval([50, 50, 50])
        original_ids = [item.citation_id for item in r.evidence]
        bound_trusted_evidence(r, budget_tokens=1)
        self.assertEqual([item.citation_id for item in r.evidence], original_ids)

    def test_citations_cannot_reference_evidence_omitted_from_the_generation_packet(self) -> None:
        r = self.make_retrieval([50, 50, 50, 50, 50])
        one_item_tokens = estimate_tokens(word_text(50, "e1w"))
        bounded = bound_trusted_evidence(r, budget_tokens=one_item_tokens * 2)  # only E1, E2 fit
        self.assertEqual([i.citation_id for i in bounded.evidence], ["E1", "E2"])

        citation_to_e4 = GroundedCitation(
            evidence_id="E4",
            claim_id="c1",
            supported_text="claims E4 supports this",
            source_metadata={},
        )
        claim = GroundedLegalClaim(
            claim_id="c1",
            text="A claim citing evidence not actually supplied to the model.",
            claim_type=ClaimType.CASE_LAW,
            citations=[citation_to_e4],
            grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
        )
        result = LegalAnswerResult(
            query="q",
            mode=AnswerMode.PROFESSIONAL,
            claims=[claim],
            citations=[citation_to_e4],
            evidence_retrieved=[item.citation_id for item in bounded.evidence],
            model_metadata=ModelGenerationMetadata(provider="fixture", configured_model_id="m", response_mode=AnswerMode.PROFESSIONAL),
            query_understanding_version="v1",
            retrieval_version="v1",
        )
        validation = validate_legal_answer_citations(result, bounded)
        self.assertFalse(validation.valid)


class EvidenceMetricsTests(unittest.TestCase):
    def test_metrics_never_include_evidence_text(self) -> None:
        r = retrieval([evidence("E1", text="sensitive legal text that must not be logged")])
        metrics = evidence_metrics(r)
        self.assertNotIn("sensitive legal text", str(metrics))
        self.assertEqual(metrics["evidence_count"], 1)
        self.assertEqual(metrics["evidence_ids"], ["E1"])
        self.assertGreater(metrics["estimated_evidence_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
