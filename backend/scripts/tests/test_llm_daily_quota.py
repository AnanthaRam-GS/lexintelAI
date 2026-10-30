"""Step 24b: daily token budgets per model (accounting, persistence, the UTC reset, skipping, the error, marking)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_answer_generation import AnswerMode, ModelProviderError  # noqa: E402
from backend.app.services.llm_daily_quota import (  # noqa: E402
    DailyCapacityReached,
    DailyLimits,
    DailyQuota,
    is_daily_limit_error,
    seconds_until_utc_reset,
)
from backend.app.services.llm_pacing import LLMPacer, ModelLimits  # noqa: E402
from backend.app.services.llm_provider_chain import PRIMARY_DAILY_CAPACITY, FallbackAnswerAdapter  # noqa: E402
from backend.scripts.tests.test_llm_pacing import (  # noqa: E402
    OTHER_MODEL,
    PUBLIC_MODEL,
    FakePacedAdapter,
    answer,
    generate,
    generate_professional,
    settings,
)

KEY = ("groq", OTHER_MODEL)
GROQ_TPD_MESSAGE = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens "
                    "per day (TPD): Limit 200000, Used 199043, Requested 1879. Please try again in 6m38.304s.")


def at(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class AccountingTests(unittest.TestCase):
    def test_tokens_and_requests_against_the_limits(self) -> None:
        quota = DailyQuota(None, clock=Clock(at("2026-10-31T10:00:00")))
        quota.configure(KEY, DailyLimits(tokens_per_day=10_000, requests_per_day=3))
        self.assertTrue(quota.can_serve(KEY, 10_000))
        quota.record(KEY, 6_000)
        self.assertTrue(quota.can_serve(KEY, 4_000))
        self.assertFalse(quota.can_serve(KEY, 4_001))
        quota.record(KEY, 100)
        quota.record(KEY, 100)
        self.assertFalse(quota.can_serve(KEY, 1))  # 3 requests per day used
        status = quota.status()["models"][f"groq/{OTHER_MODEL}"]
        self.assertEqual((status["tokens_used"], status["tokens_remaining"], status["requests_used"]), (6_200, 3_800, 3))

    def test_untracked_models_are_not_limited(self) -> None:
        quota = DailyQuota(None)
        self.assertTrue(quota.can_serve(("gemini", "m"), 10**9))
        quota.record(("gemini", "m"), 5)  # ignored
        self.assertEqual(quota.status()["models"], {})


class PersistenceTests(unittest.TestCase):
    def test_usage_and_marks_survive_a_restart(self) -> None:
        clock = Clock(at("2026-10-31T10:00:00"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime" / "llm_daily_usage.json"
            first = DailyQuota(path, clock=clock)
            first.configure(KEY, DailyLimits(200_000))
            first.record(KEY, 150_000)
            first.mark_exhausted(("groq", PUBLIC_MODEL), 600)
            restarted = DailyQuota(path, clock=clock)
            restarted.configure(KEY, DailyLimits(200_000))
            restarted.configure(("groq", PUBLIC_MODEL), DailyLimits(200_000))
            self.assertFalse(restarted.can_serve(KEY, 60_000))
            self.assertTrue(restarted.can_serve(KEY, 50_000))
            self.assertFalse(restarted.can_serve(("groq", PUBLIC_MODEL), 1))
            stored = json.loads(path.read_text())
            self.assertEqual(stored["day"], "2026-10-31")
            self.assertNotIn("prompt", path.read_text())  # usage numbers only

    def test_an_unreadable_file_starts_a_new_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.json"
            path.write_text("{not json")
            quota = DailyQuota(path)
            quota.configure(KEY, DailyLimits(100))
            self.assertTrue(quota.can_serve(KEY, 100))


class ResetBoundaryTests(unittest.TestCase):
    def test_the_count_resets_at_utc_midnight(self) -> None:
        clock = Clock(at("2026-10-31T23:59:30"))
        quota = DailyQuota(None, clock=clock)
        quota.configure(KEY, DailyLimits(10_000))
        quota.record(KEY, 10_000)
        self.assertFalse(quota.can_serve(KEY, 1))
        self.assertEqual(round(quota.seconds_until_available(KEY)), 30)
        self.assertEqual(round(seconds_until_utc_reset(clock.now)), 30)
        clock.now = at("2026-11-01T00:00:01")
        self.assertTrue(quota.can_serve(KEY, 10_000))
        self.assertEqual(quota.status()["day_utc"], "2026-11-01")

    def test_a_provider_mark_beyond_midnight_is_kept(self) -> None:
        clock = Clock(at("2026-10-31T23:50:00"))
        quota = DailyQuota(None, clock=clock)
        quota.configure(KEY, DailyLimits(10_000))
        quota.mark_exhausted(KEY, 1_800)  # the provider says 30 minutes: past midnight
        clock.now = at("2026-11-01T00:05:00")
        self.assertFalse(quota.can_serve(KEY, 1))
        self.assertEqual(round(quota.seconds_until_available(KEY)), 900)
        clock.now = at("2026-11-01T00:21:00")
        self.assertTrue(quota.can_serve(KEY, 1))

    def test_a_mark_without_retry_after_lasts_until_the_reset(self) -> None:
        clock = Clock(at("2026-10-31T22:00:00"))
        quota = DailyQuota(None, clock=clock)
        quota.configure(KEY, DailyLimits(10_000))
        quota.mark_exhausted(KEY, None)
        self.assertEqual(round(quota.seconds_until_available(KEY)), 7_200)


def rate_limited_daily(prefix: str, retry_after: float | None) -> ModelProviderError:
    error = ModelProviderError(f"{prefix}_RATE_LIMIT", "rate limited", http_status=429, provider_code="tokens",
                               provider_message=GROQ_TPD_MESSAGE)
    error.retry_after_seconds = retry_after
    return error


class ChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pacer = LLMPacer()
        for model in (PUBLIC_MODEL, OTHER_MODEL):
            self.pacer.configure(("groq", model), ModelLimits(600_000, 600))
        self.clock = Clock(at("2026-10-31T12:00:00"))
        self.quota = DailyQuota(None, clock=self.clock)

    def chain(self, primary, fallback, **values):
        return FallbackAnswerAdapter(primary, fallback, primary_name="groq", fallback_name="groq_backup",
                                     settings=settings(legalai_groq_tokens_per_day=200_000, **values), pacer=self.pacer, quota=self.quota)

    def test_the_daily_limit_error_is_recognised(self) -> None:
        self.assertTrue(is_daily_limit_error(rate_limited_daily("GROQ", 398)))
        minute = ModelProviderError("GROQ_RATE_LIMIT", "x", http_status=429, provider_message="Rate limit reached on tokens per minute (TPM)")
        self.assertFalse(is_daily_limit_error(minute))
        self.assertFalse(is_daily_limit_error(ModelProviderError("GROQ_PROVIDER_ERROR", GROQ_TPD_MESSAGE, http_status=503)))

    def test_usage_is_recorded_from_the_provider_tokens(self) -> None:
        response = answer("groq", PUBLIC_MODEL)
        response.model_metadata.prompt_tokens, response.model_metadata.completion_tokens = 4_000, 1_200
        generate(self.chain(FakePacedAdapter("groq", PUBLIC_MODEL, [response]), None))
        self.assertEqual(self.quota.status()["models"][f"groq/{PUBLIC_MODEL}"]["tokens_used"], 5_200)

    def test_an_exhausted_primary_is_skipped_for_the_public_fallback(self) -> None:
        self.quota.configure(("groq", PUBLIC_MODEL), DailyLimits(200_000))
        self.quota.record(("groq", PUBLIC_MODEL), 199_900)
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [answer("groq_backup", OTHER_MODEL)])
        response = generate(self.chain(primary, fallback))
        self.assertEqual((len(primary.calls), len(fallback.calls)), (0, 1))
        self.assertEqual(response.model_metadata.fallback_reason, PRIMARY_DAILY_CAPACITY)

    def test_nothing_can_serve_gives_daily_capacity_reached_with_retry_after(self) -> None:
        self.quota.configure(KEY, DailyLimits(200_000))
        self.quota.record(KEY, 200_000)
        primary = FakePacedAdapter("groq", OTHER_MODEL, [])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [answer("groq_backup", PUBLIC_MODEL)])  # never allowed: professional
        with self.assertRaises(DailyCapacityReached) as caught:
            generate_professional(self.chain(primary, fallback))
        self.assertEqual(caught.exception.retry_after_seconds, 12 * 3600)  # until 00:00 UTC
        self.assertEqual((len(primary.calls), len(fallback.calls)), (0, 0))

    def test_a_provider_daily_error_marks_the_model_and_falls_back_for_public(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [rate_limited_daily("GROQ", 398)])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [answer("groq_backup", OTHER_MODEL), answer("groq_backup", OTHER_MODEL)])
        target = self.chain(primary, fallback)
        generate(target)
        self.assertEqual(self.quota.status()["models"][f"groq/{PUBLIC_MODEL}"]["exhausted_for_seconds"], 398)
        generate(target)  # the next request skips the exhausted model without calling it
        self.assertEqual((len(primary.calls), len(fallback.calls)), (1, 2))

    def test_a_provider_daily_error_on_a_professional_query_is_daily_capacity_reached(self) -> None:
        primary = FakePacedAdapter("groq", OTHER_MODEL, [rate_limited_daily("GROQ", 398)])
        with self.assertRaises(DailyCapacityReached) as caught:
            generate_professional(self.chain(primary, FakePacedAdapter("groq_backup", PUBLIC_MODEL, [])))
        self.assertEqual(caught.exception.retry_after_seconds, 398)


class EnvExampleTests(unittest.TestCase):
    def test_the_env_example_parses_as_settings(self) -> None:
        """README setup copies .env.example to .env: every value in it must be accepted (an empty integer is not)."""
        from backend.app.core.config import Settings

        settings_from_example = Settings(_env_file=REPO_ROOT / ".env.example")
        self.assertEqual(settings_from_example.legalai_groq_tokens_per_day, 200_000)
        self.assertIsNone(settings_from_example.legalai_groq_requests_per_day)
        self.assertFalse(settings_from_example.legalai_professional_fallback_enabled)


class ApiTests(unittest.TestCase):
    def test_daily_capacity_reached_is_a_503_with_retry_after(self) -> None:
        from backend.app.api import query as query_api
        from backend.app.services.legal_query_understanding import understand_legal_query
        from backend.app.services.product_context_budget import resolve_product_context_budget
        from backend.scripts.tests.test_legal_answer_foundation import retrieval

        class Exhausted:
            manages_generation_slot = True
            configured_model_id = "m"

            def generate_structured_answer(self, prompt, *, schema, mode):
                raise DailyCapacityReached(3_600)

        with self.assertRaises(query_api.QueryExecutionError) as caught:
            query_api._attempt_generation(
                query="bail", query_tokens=1, understanding=understand_legal_query("bail"), retrieval=retrieval(),
                mode=AnswerMode.PROFESSIONAL, adapter=Exhausted(), product_budget=resolve_product_context_budget(settings()),
                tier=query_api.ContextTier.NORMAL, private_context_builder=None, generation_limit=(1, 0.0),
            )
        self.assertEqual((caught.exception.code, caught.exception.status_code, caught.exception.retry_after),
                         ("DAILY_CAPACITY_REACHED", 503, 3_600))

    def test_health_reports_daily_usage(self) -> None:
        import backend.main as main_module
        from backend.app.services import llm_daily_quota

        quota = DailyQuota(None)
        quota.configure(KEY, DailyLimits(200_000))
        quota.record(KEY, 1_234)
        llm_daily_quota.reset_default_quota(quota)
        try:
            with patch.object(main_module, "check_db_connection", return_value=(True, "connected")):
                daily = main_module.health_check()["llm_daily"]
        finally:
            llm_daily_quota.reset_default_quota(None)
        self.assertEqual(set(daily), {"day_utc", "resets_in_seconds", "models"})
        self.assertEqual(daily["models"][f"groq/{OTHER_MODEL}"]["tokens_used"], 1_234)
        self.assertEqual(daily["models"][f"groq/{OTHER_MODEL}"]["tokens_remaining"], 198_766)


if __name__ == "__main__":
    unittest.main()
