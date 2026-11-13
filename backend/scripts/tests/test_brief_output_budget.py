"""Step 26b: brief-mode output cap and request-size arithmetic (mocked; no provider, no database)."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from backend.app.api import query as query_api
from backend.app.core.config import Settings
from backend.app.services.groq_answer_adapter import GroqAnswerAdapter
from backend.app.services.legal_answer_generation import AnswerMode
from backend.app.services.llm_output_cap import effective_max_output_tokens, output_token_cap
from backend.app.services.token_budget import estimate_tokens


def groq_settings(**overrides) -> Settings:
    values = {"legalai_llm_provider": "groq", "legalai_groq_max_request_tokens": 8000, "legalai_groq_token_estimate_factor": 1.57,
              "legalai_llm_max_output_tokens": 2048, "legalai_brief_max_output_tokens": 3000}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def retrieval_with(*texts: str):
    evidence = [SimpleNamespace(text=text, rank=i + 1, model_copy=lambda update, t=text, i=i: SimpleNamespace(text=update["text"], rank=i + 1))
                for i, text in enumerate(texts)]
    retrieval = SimpleNamespace(evidence=evidence)
    retrieval.model_copy = lambda update: SimpleNamespace(evidence=update["evidence"], model_copy=retrieval.model_copy)
    return retrieval


SENTENCES = " ".join(f"Sentence number {i} of the trusted judgment excerpt talks about bail and custody." for i in range(120))


class GuardArithmeticTests(unittest.TestCase):
    def test_the_guard_reserves_the_brief_cap_instead_of_the_default(self) -> None:
        settings = groq_settings()
        prompt = "x " * 4000
        default = query_api.request_size_guard(settings, AnswerMode.PROFESSIONAL)
        brief = query_api.request_size_guard(settings, AnswerMode.PROFESSIONAL, 3000)
        self.assertEqual((default.max_output_tokens, brief.max_output_tokens), (2048, 3000))
        self.assertEqual(brief.estimated_request_tokens(prompt, AnswerMode.PROFESSIONAL)
                         - default.estimated_request_tokens(prompt, AnswerMode.PROFESSIONAL), 952)

    def test_the_live_charge_sheet_numbers(self) -> None:
        # Step 26b accounting: prompt + schema estimated at 3518 tokens after trimming trusted evidence to one item.
        factor, ceiling, prompt_and_schema = 1.57, 8000, 3518
        self.assertLessEqual(round(prompt_and_schema * factor) + 2048, ceiling)       # 7571: fits, but output capped at 2048
        overflow = round(prompt_and_schema * factor) + 3000 - ceiling                  # 523 over with the brief cap
        self.assertEqual(overflow, 523)
        self.assertEqual(math.ceil(overflow / factor) + 25, 359)                       # tokens cut from the last trusted item


class OutputCapTests(unittest.TestCase):
    def test_no_cap_outside_a_brief_run(self) -> None:
        self.assertEqual(effective_max_output_tokens(2048), 2048)

    def test_the_cap_applies_inside_and_is_reset_after(self) -> None:
        with output_token_cap(3000):
            self.assertEqual(effective_max_output_tokens(2048), 3000)
            with output_token_cap(None):
                self.assertEqual(effective_max_output_tokens(2048), 2048)
            self.assertEqual(effective_max_output_tokens(2048), 3000)
        self.assertEqual(effective_max_output_tokens(2048), 2048)

    def test_the_groq_adapter_sends_the_cap(self) -> None:
        adapter = GroqAnswerAdapter(groq_settings())
        self.assertEqual(adapter.max_output_tokens, 2048)
        with output_token_cap(3000):
            self.assertEqual(adapter.max_output_tokens, 3000)


class ShortenLastTrustedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = query_api.request_size_guard(groq_settings(), AnswerMode.PROFESSIONAL, 3000)

    def prompt_for(self, retrieval) -> str:
        return "instructions " * 1500 + retrieval.evidence[0].text

    def test_the_single_item_is_shortened_just_enough_to_fit(self) -> None:
        retrieval = retrieval_with(SENTENCES)
        prompt = self.prompt_for(retrieval)
        self.assertFalse(self.guard.fits(prompt, AnswerMode.PROFESSIONAL))
        shortened = query_api.shortened_last_trusted(retrieval, prompt, AnswerMode.PROFESSIONAL, self.guard)
        self.assertIsNotNone(shortened)
        text = shortened.evidence[0].text
        self.assertLess(estimate_tokens(text), estimate_tokens(SENTENCES))
        self.assertTrue(SENTENCES.startswith(text.rstrip(". ")[:200]))  # an excerpt of the same text, from the start
        self.assertTrue(self.guard.fits("instructions " * 1500 + text, AnswerMode.PROFESSIONAL))

    def test_nothing_is_shortened_when_the_request_fits(self) -> None:
        retrieval = retrieval_with("A short trusted excerpt.")
        self.assertIsNone(query_api.shortened_last_trusted(retrieval, "short prompt", AnswerMode.PROFESSIONAL, self.guard))

    def test_never_below_the_minimum_excerpt(self) -> None:
        retrieval = retrieval_with(SENTENCES)
        prompt = "instructions " * 4000 + SENTENCES  # far over: the excerpt would fall under the minimum
        self.assertIsNone(query_api.shortened_last_trusted(retrieval, prompt, AnswerMode.PROFESSIONAL, self.guard))

    def test_only_a_single_remaining_item_is_shortened(self) -> None:
        retrieval = retrieval_with(SENTENCES, SENTENCES)
        self.assertIsNone(query_api.shortened_last_trusted(retrieval, self.prompt_for(retrieval), AnswerMode.PROFESSIONAL, self.guard))


if __name__ == "__main__":
    unittest.main()
