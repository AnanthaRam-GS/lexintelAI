"""Step 23: per-model pacing, the FIFO queue, rate-limit handling in the provider chain (no network, no database)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.rate_limit import GenerationSlots  # noqa: E402
from backend.app.services import inference_lock  # noqa: E402
from backend.app.services.legal_answer_generation import (  # noqa: E402
    AnswerMode,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    PublicLegalAnswer,
)
from backend.app.services.llm_pacing import (  # noqa: E402
    LLMPacer,
    ModelLimits,
    PacingTimeout,
    TokenBucket,
    parse_duration_seconds,
    retry_after_seconds,
)
from backend.app.services.llm_provider_chain import (  # noqa: E402
    PRIMARY_AT_CAPACITY,
    RATE_LIMIT_RETRY,
    FallbackAnswerAdapter,
    GenerationQueueTimeout,
    request_tokens,
)

PUBLIC_MODEL, OTHER_MODEL = "openai/gpt-oss-20b", "openai/gpt-oss-120b"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class BucketArithmeticTests(unittest.TestCase):
    def test_refill_wait_and_take(self) -> None:
        bucket = TokenBucket(ModelLimits(tokens_per_minute=6000, requests_per_minute=30))
        bucket.updated_at = 0.0
        self.assertEqual((bucket.token_rate, bucket.request_rate), (100.0, 0.5))
        self.assertEqual(bucket.wait_seconds(6000, 0.0), 0.0)
        bucket.take(5000, 0.0)
        self.assertEqual(bucket.tokens, 1000.0)
        self.assertAlmostEqual(bucket.wait_seconds(3000, 0.0), 20.0)  # 2,000 missing at 100 tokens/s
        self.assertAlmostEqual(bucket.wait_seconds(3000, 20.0), 0.0)
        bucket.refresh(1000.0)
        self.assertEqual(bucket.tokens, 6000.0)  # never above the minute's limit

    def test_requests_per_minute_also_bound(self) -> None:
        bucket = TokenBucket(ModelLimits(tokens_per_minute=1_000_000, requests_per_minute=2))
        bucket.updated_at = 0.0
        bucket.take(1, 0.0)
        bucket.take(1, 0.0)
        self.assertAlmostEqual(bucket.wait_seconds(1, 0.0), 30.0)  # 1 request at 2 per minute

    def test_a_request_larger_than_the_minute_waits_for_a_full_bucket(self) -> None:
        bucket = TokenBucket(ModelLimits(tokens_per_minute=8000, requests_per_minute=30))
        bucket.updated_at = 0.0
        self.assertEqual(bucket.cost_for(9000), 8000.0)
        self.assertEqual(bucket.wait_seconds(9000, 0.0), 0.0)


class HeaderTests(unittest.TestCase):
    def test_durations(self) -> None:
        cases = {"44.655s": 44.655, "1m26.4s": 86.4, "705ms": 0.705, "2h3m": 7380.0, "7": 7.0, "0.5": 0.5}
        for text, seconds in cases.items():
            self.assertAlmostEqual(parse_duration_seconds(text), seconds, msg=text)
        for bad in (None, "", "soon", "5x"):
            self.assertIsNone(parse_duration_seconds(bad))
        self.assertEqual(retry_after_seconds({"Retry-After": "12"}), 12.0)
        self.assertEqual(retry_after_seconds({"x-ratelimit-reset-tokens": "1m0s"}), 60.0)
        self.assertIsNone(retry_after_seconds({}))

    def test_remaining_tokens_replace_the_estimate(self) -> None:
        clock = FakeClock()
        pacer = LLMPacer(clock=clock)
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(8000, 30))
        pacer.observe(key, {"x-ratelimit-remaining-tokens": "3920", "x-ratelimit-reset-tokens": "30s"})
        self.assertEqual(pacer.status()["models"][f"groq/{PUBLIC_MODEL}"]["tokens_available"], 3920)
        self.assertAlmostEqual(pacer.wait_seconds(key, 7000), (7000 - 3920) / (8000 / 60))

    def test_no_daily_requests_left_blocks_until_the_reset(self) -> None:
        clock = FakeClock()
        pacer = LLMPacer(clock=clock)
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(8000, 30))
        pacer.observe(key, {"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "2m"})
        self.assertAlmostEqual(pacer.wait_seconds(key, 10), 120.0)

    def test_a_429_blocks_the_bucket_for_retry_after(self) -> None:
        clock = FakeClock()
        pacer = LLMPacer(clock=clock)
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(8000, 30))
        pacer.block(key, 9.0)
        self.assertAlmostEqual(pacer.wait_seconds(key, 1), 9.0)
        clock.now += 9.0
        self.assertGreaterEqual(pacer.status()["models"][f"groq/{PUBLIC_MODEL}"]["tokens_available"], 0)
        self.assertEqual(pacer.wait_seconds(key, 1), 0.0)  # 9 s at 133 tokens/s refilled the 1 token

    def test_unpaced_keys_pass_through(self) -> None:
        pacer = LLMPacer()
        self.assertEqual(pacer.acquire([(("gemini", "m"), 10**9)], timeout_seconds=0), (("gemini", "m"), 0.0))
        self.assertTrue(pacer.has_capacity(("gemini", "m"), 10**9))


class QueueTests(unittest.TestCase):
    """Real time, small limits: 600 tokens per minute is 10 tokens per second."""

    def setUp(self) -> None:
        self.pacer = LLMPacer()
        self.key = ("groq", PUBLIC_MODEL)
        self.pacer.configure(self.key, ModelLimits(tokens_per_minute=600, requests_per_minute=600))
        self.pacer.observe(self.key, {"x-ratelimit-remaining-tokens": "0"})

    def test_fifo_order(self) -> None:
        order: list[int] = []

        def request(number: int) -> None:
            self.pacer.acquire([(self.key, 2)], timeout_seconds=5)
            order.append(number)

        threads = []
        for number in range(5):
            thread = threading.Thread(target=request, args=(number,))
            thread.start()
            threads.append(thread)
            time.sleep(0.02)  # arrive in order
        self.assertEqual(self.pacer.status()["queue_depth"], 5 - len(order))
        for thread in threads:
            thread.join(5)
        self.assertEqual(order, [0, 1, 2, 3, 4])

    def test_status_reports_depth_and_estimated_wait(self) -> None:
        done = threading.Event()

        def request() -> None:
            self.pacer.acquire([(self.key, 20)], timeout_seconds=5)
            done.set()

        thread = threading.Thread(target=request)
        thread.start()
        time.sleep(0.05)
        status = self.pacer.status()
        self.assertEqual(status["queue_depth"], 1)
        self.assertGreater(status["estimated_wait_seconds"], 1.0)
        self.assertLessEqual(status["estimated_wait_seconds"], 2.0)
        thread.join(5)
        self.assertTrue(done.is_set())
        self.assertEqual(self.pacer.status()["queue_depth"], 0)

    def test_timeout(self) -> None:
        started = time.monotonic()
        with self.assertRaises(PacingTimeout) as caught:
            self.pacer.acquire([(self.key, 300)], timeout_seconds=0.2)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertGreaterEqual(caught.exception.retry_after_seconds, 29)  # 300 tokens at 10/s
        self.assertEqual(self.pacer.status()["queue_depth"], 0)

    def test_the_head_takes_the_first_candidate_with_capacity(self) -> None:
        other = ("groq", OTHER_MODEL)
        self.pacer.configure(other, ModelLimits(600, 600))
        key, waited = self.pacer.acquire([(self.key, 100), (other, 100)], timeout_seconds=1)
        self.assertEqual((key, waited < 0.1), (other, True))


def answer(provider: str, model: str) -> LegalAnswerModelResponse:
    body = '{"answer": {"summary": "s"}, "summary": "s", "claims": []}'
    metadata = ModelGenerationMetadata(provider=provider, configured_model_id=model, response_mode=AnswerMode.PUBLIC)
    return LegalAnswerModelResponse(raw_response=body, parsed_response=None, model_metadata=metadata, timings={})


def rate_limited(prefix: str, retry_after: float | None) -> ModelProviderError:
    error = ModelProviderError(f"{prefix}_RATE_LIMIT", "rate limited", http_status=429)
    error.retry_after_seconds = retry_after
    return error


class FakePacedAdapter:
    max_output_tokens = 100

    def __init__(self, name: str, model: str, outcomes: list) -> None:
        self.name, self.model, self.outcomes, self.calls = name, model, list(outcomes), []

    def rate_limit_key(self, mode):
        return ("groq", self.model)

    def generate_structured_answer(self, prompt, *, schema, mode):
        self.calls.append(time.monotonic())
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def settings(**values) -> Settings:
    base = dict(_env_file=None, app_env="test", legalai_groq_tokens_per_minute=600_000, legalai_groq_requests_per_minute=600,
                legalai_groq_token_estimate_factor=1.0, legalai_llm_queue_max_wait_seconds=5, llm_max_concurrent_generations=2,
                llm_generation_wait_seconds=5)
    return Settings(**{**base, **values})


def chain(primary, fallback, pacer, *, slots=None, **values) -> FallbackAnswerAdapter:
    return FallbackAnswerAdapter(primary, fallback, primary_name="groq", fallback_name="groq_backup", settings=settings(**values),
                                 pacer=pacer, slots=slots)


def generate(target):
    return target.generate_structured_answer("prompt " * 50, schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)


class ChainRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pacer = LLMPacer()

    def drain(self, model: str) -> None:
        self.pacer.observe(("groq", model), {"x-ratelimit-remaining-tokens": "0"})

    def test_immediate_fallback_on_429_when_the_other_model_has_capacity(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [rate_limited("GROQ", 30)])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [answer("groq_backup", OTHER_MODEL)])
        started = time.monotonic()
        response = generate(chain(primary, fallback, self.pacer))
        self.assertLess(time.monotonic() - started, 1.0)  # no wait, no quick retry of the primary
        self.assertEqual((len(primary.calls), len(fallback.calls)), (1, 1))
        metadata = response.model_metadata
        self.assertEqual((metadata.provider, metadata.fallback_used, metadata.fallback_reason), ("groq_backup", True, "GROQ_RATE_LIMIT"))
        self.assertEqual(response.timings["rate_limit_retries"], 0)
        self.assertGreaterEqual(self.pacer.wait_seconds(("groq", PUBLIC_MODEL), 1), 29)  # blocked for retry-after

    def test_waits_for_retry_after_then_retries_once_never_sooner(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [rate_limited("GROQ", 0.6), answer("groq", PUBLIC_MODEL)])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [])
        target = chain(primary, fallback, self.pacer)
        self.pacer.configure(("groq", OTHER_MODEL), ModelLimits(600, 600))
        self.drain(OTHER_MODEL)  # the fallback has no capacity for a while (10 tokens/s)
        response = generate(target)
        self.assertEqual((len(primary.calls), len(fallback.calls)), (2, 0))
        self.assertGreaterEqual(primary.calls[1] - primary.calls[0], 0.6)
        self.assertEqual(response.timings["rate_limit_retries"], 1)
        self.assertGreaterEqual(response.timings["rate_limit_wait_ms"], 590)
        self.assertIn(RATE_LIMIT_RETRY, response.model_metadata.retry_reasons)
        self.assertFalse(response.model_metadata.fallback_used)

    def test_retry_after_beyond_the_queue_wait_is_model_busy_at_once(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [rate_limited("GROQ", 60)])
        target = FallbackAnswerAdapter(primary, None, primary_name="groq", fallback_name=None, settings=settings(), pacer=self.pacer)
        started = time.monotonic()
        with self.assertRaises(GenerationQueueTimeout) as caught:
            generate(target)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(caught.exception.retry_after_seconds, 60)
        self.assertEqual(len(primary.calls), 1)

    def test_a_429_without_headers_waits_a_whole_window(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [rate_limited("GROQ", None)])
        target = FallbackAnswerAdapter(primary, None, primary_name="groq", fallback_name=None, settings=settings(), pacer=self.pacer)
        with self.assertRaises(GenerationQueueTimeout) as caught:
            generate(target)
        self.assertEqual(caught.exception.retry_after_seconds, 60)

    def test_the_fallback_answers_when_only_it_has_capacity(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [answer("groq_backup", OTHER_MODEL)])
        target = chain(primary, fallback, self.pacer)
        self.pacer.configure(("groq", PUBLIC_MODEL), ModelLimits(600, 600))
        self.drain(PUBLIC_MODEL)
        response = generate(target)
        self.assertEqual((len(primary.calls), response.model_metadata.fallback_reason), (0, PRIMARY_AT_CAPACITY))

    def test_queue_timeout_when_no_model_has_capacity(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [])
        target = FallbackAnswerAdapter(primary, None, primary_name="groq", fallback_name=None,
                                       settings=settings(legalai_groq_tokens_per_minute=600, legalai_llm_queue_max_wait_seconds=0.3),
                                       pacer=self.pacer)
        target.generate_structured_answer  # noqa: B018
        self.pacer.configure(("groq", PUBLIC_MODEL), ModelLimits(600, 600))
        self.drain(PUBLIC_MODEL)
        with self.assertRaises(GenerationQueueTimeout) as caught:
            generate(target)
        self.assertGreaterEqual(caught.exception.waited_seconds, 0.29)
        self.assertGreaterEqual(caught.exception.retry_after_seconds, 1)
        self.assertEqual(primary.calls, [])

    def test_queued_requests_wait_then_succeed_with_the_wait_recorded(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [answer("groq", PUBLIC_MODEL)])
        target = FallbackAnswerAdapter(primary, None, primary_name="groq", fallback_name=None, settings=settings(), pacer=self.pacer)
        key = ("groq", PUBLIC_MODEL)
        self.pacer.configure(key, ModelLimits(600_000, 600))
        self.pacer.block(key, 0.4)
        response = generate(target)
        self.assertGreaterEqual(response.timings["queue_wait_ms"], 390)
        self.assertIsNone(response.model_metadata.primary_provider)  # no fallback configured: chain fields untouched

    def test_request_tokens_are_the_guard_estimate_plus_the_output_limit(self) -> None:
        import json

        from backend.app.services.groq_answer_adapter import groq_payload_schema
        from backend.app.services.token_budget import estimate_tokens

        adapter = FakePacedAdapter("groq", PUBLIC_MODEL, [])
        prompt = "word " * 400
        expected = round((estimate_tokens(prompt) + estimate_tokens(json.dumps(groq_payload_schema(PublicLegalAnswer)))) * 1.57) + 100
        self.assertEqual(request_tokens(adapter, prompt, PublicLegalAnswer, settings(legalai_groq_token_estimate_factor=1.57)), expected)


def generate_professional(target):
    from backend.app.services.legal_answer_generation import ProfessionalLegalBrief

    return target.generate_structured_answer("prompt " * 50, schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)


class FallbackPolicyTests(unittest.TestCase):
    """Step 24: professional answers wait for the primary (up to the primary wait); public answers fall back at once."""

    def setUp(self) -> None:
        self.pacer = LLMPacer()
        for model in (PUBLIC_MODEL, OTHER_MODEL):
            self.pacer.configure(("groq", model), ModelLimits(600_000, 600))

    def test_professional_waits_for_the_primary_while_the_fallback_is_free(self) -> None:
        primary = FakePacedAdapter("groq", OTHER_MODEL, [answer("groq", OTHER_MODEL)])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [])
        self.pacer.block(("groq", OTHER_MODEL), 0.4)
        response = generate_professional(chain(primary, fallback, self.pacer))
        self.assertEqual((len(primary.calls), len(fallback.calls)), (1, 0))
        self.assertFalse(response.model_metadata.fallback_used)
        self.assertEqual(response.timings["fallback_policy_wait_for_primary"], 1.0)
        self.assertGreaterEqual(response.timings["primary_wait_ms"], 390)

    def test_professional_falls_back_after_the_primary_wait(self) -> None:
        primary = FakePacedAdapter("groq", OTHER_MODEL, [])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [answer("groq_backup", PUBLIC_MODEL)])
        self.pacer.block(("groq", OTHER_MODEL), 30)
        started = time.monotonic()
        response = generate_professional(chain(primary, fallback, self.pacer, legalai_professional_primary_max_wait_seconds=0.3))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.29)
        self.assertLess(elapsed, 2.0)
        self.assertEqual((len(primary.calls), len(fallback.calls)), (0, 1))
        metadata = response.model_metadata
        self.assertEqual((metadata.fallback_used, metadata.fallback_reason), (True, PRIMARY_AT_CAPACITY))
        self.assertAlmostEqual(response.timings["primary_wait_ms"], 300, delta=60)

    def test_public_falls_back_at_once(self) -> None:
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [])
        fallback = FakePacedAdapter("groq_backup", OTHER_MODEL, [answer("groq_backup", OTHER_MODEL)])
        self.pacer.block(("groq", PUBLIC_MODEL), 30)
        started = time.monotonic()
        response = generate(chain(primary, fallback, self.pacer))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(response.timings["fallback_policy_wait_for_primary"], 0.0)
        self.assertNotIn("primary_wait_ms", response.timings)
        self.assertTrue(response.model_metadata.fallback_used)

    def test_professional_429_inside_the_window_is_waited_out_on_the_primary(self) -> None:
        primary = FakePacedAdapter("groq", OTHER_MODEL, [rate_limited("GROQ", 0.4), answer("groq", OTHER_MODEL)])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [])
        response = generate_professional(chain(primary, fallback, self.pacer))
        self.assertEqual((len(primary.calls), len(fallback.calls)), (2, 0))
        self.assertGreaterEqual(primary.calls[1] - primary.calls[0], 0.4)
        self.assertEqual(response.timings["rate_limit_retries"], 1)
        self.assertFalse(response.model_metadata.fallback_used)

    def test_professional_429_beyond_the_window_falls_back(self) -> None:
        primary = FakePacedAdapter("groq", OTHER_MODEL, [rate_limited("GROQ", 120)])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [answer("groq_backup", PUBLIC_MODEL)])
        response = generate_professional(chain(primary, fallback, self.pacer))
        self.assertEqual((len(primary.calls), len(fallback.calls)), (1, 1))
        self.assertEqual(response.model_metadata.fallback_reason, "GROQ_RATE_LIMIT")

    def test_the_api_backend_names_the_policy(self) -> None:
        from backend.app.api import query as query_api
        from backend.app.services.legal_answer_generation import generate_legal_answer
        from backend.app.services.legal_query_understanding import understand_legal_query
        from backend.scripts.tests.test_legal_answer_foundation import retrieval

        primary = FakePacedAdapter("groq", OTHER_MODEL, [answer("groq", OTHER_MODEL)])
        fallback = FakePacedAdapter("groq_backup", PUBLIC_MODEL, [])
        result = generate_legal_answer(understand_legal_query("bail"), retrieval(), mode=AnswerMode.PROFESSIONAL,
                                       adapter=chain(primary, fallback, self.pacer), prompt="p")
        backend = query_api.answer_backend(result)
        self.assertEqual(backend["fallback_policy"], "wait_for_primary")
        self.assertIsNotNone(backend["primary_wait_ms"])
        self.assertIn("fallback_policy", query_api.history_payload({}, result)["generation"])
        self.assertEqual(Settings.model_fields["legalai_professional_primary_max_wait_seconds"].default, 45.0)


class NoDeadlockTests(unittest.TestCase):
    def test_a_queued_request_holds_no_slot_and_never_the_inference_lock(self) -> None:
        pacer = LLMPacer()
        slots = GenerationSlots()
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(600_000, 600))
        pacer.block(key, 0.5)
        primary = FakePacedAdapter("groq", PUBLIC_MODEL, [answer("groq", PUBLIC_MODEL)])
        target = FallbackAnswerAdapter(primary, None, primary_name="groq", fallback_name=None,
                                       settings=settings(llm_max_concurrent_generations=1), pacer=pacer, slots=slots)
        result: dict = {}
        worker = threading.Thread(target=lambda: result.setdefault("response", generate(target)))
        worker.start()
        time.sleep(0.1)
        self.assertEqual(pacer.status()["queue_depth"], 1)
        # While it waits: the only generation slot is free, and the model inference lock is free.
        with slots.slot(1, 0.0) as acquired:
            self.assertTrue(acquired)
        free = inference_lock._lock.acquire(blocking=False)  # held by no other thread
        self.assertTrue(free)
        inference_lock._lock.release()
        worker.join(5)
        self.assertIn("response", result)

    def test_many_concurrent_requests_finish_with_few_slots_and_the_inference_lock_busy(self) -> None:
        pacer = LLMPacer()
        slots = GenerationSlots()
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(tokens_per_minute=600_000, requests_per_minute=120))  # 2 requests per second
        pacer.block(key, 0.2)

        class SlowAdapter(FakePacedAdapter):
            def generate_structured_answer(self, prompt, *, schema, mode):
                time.sleep(0.05)
                return answer("groq", PUBLIC_MODEL)

        target = FallbackAnswerAdapter(SlowAdapter("groq", PUBLIC_MODEL, []), None, primary_name="groq", fallback_name=None,
                                       settings=settings(llm_max_concurrent_generations=2, legalai_llm_queue_max_wait_seconds=10),
                                       pacer=pacer, slots=slots)
        finished: list[int] = []
        stop = threading.Event()

        def hold_inference_lock() -> None:  # local model work running alongside (retrieval of other requests)
            while not stop.is_set():
                with inference_lock.inference_slot("test-model"):
                    time.sleep(0.02)

        holder = threading.Thread(target=hold_inference_lock)
        holder.start()
        workers = [threading.Thread(target=lambda n=n: (generate(target), finished.append(n))) for n in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
        stop.set()
        holder.join(5)
        self.assertEqual(sorted(finished), list(range(6)))
        self.assertEqual(pacer.status()["queue_depth"], 0)


class ApiTests(unittest.TestCase):
    def test_queue_timeout_is_model_busy_with_retry_after(self) -> None:
        from backend.app.api import query as query_api
        from backend.app.services.product_context_budget import resolve_product_context_budget
        from backend.app.services.legal_query_understanding import understand_legal_query
        from backend.scripts.tests.test_legal_answer_foundation import retrieval

        class Busy:
            manages_generation_slot = True
            configured_model_id = "m"

            def generate_structured_answer(self, prompt, *, schema, mode):
                raise GenerationQueueTimeout(42, 90.0)

        with self.assertRaises(query_api.QueryExecutionError) as caught:
            query_api._attempt_generation(
                query="bail", query_tokens=1, understanding=understand_legal_query("bail"), retrieval=retrieval(),
                mode=AnswerMode.PUBLIC, adapter=Busy(), product_budget=resolve_product_context_budget(settings()),
                tier=query_api.ContextTier.NORMAL, private_context_builder=None, generation_limit=(1, 0.0),
            )
        self.assertEqual((caught.exception.code, caught.exception.status_code, caught.exception.retry_after), ("MODEL_BUSY", 503, 42))

    def test_backend_record_carries_the_pacing_fields(self) -> None:
        from backend.app.api import query as query_api
        from backend.app.services.legal_answer_generation import generate_legal_answer
        from backend.app.services.legal_query_understanding import understand_legal_query
        from backend.scripts.tests.test_legal_answer_foundation import retrieval

        pacer = LLMPacer()
        key = ("groq", PUBLIC_MODEL)
        pacer.configure(key, ModelLimits(600_000, 600))
        pacer.block(key, 0.2)
        target = FallbackAnswerAdapter(FakePacedAdapter("groq", PUBLIC_MODEL, [answer("groq", PUBLIC_MODEL)]), None,
                                       primary_name="groq", fallback_name=None, settings=settings(), pacer=pacer)
        result = generate_legal_answer(understand_legal_query("bail"), retrieval(), mode=AnswerMode.PUBLIC, adapter=target, prompt="p")
        backend = query_api.answer_backend(result)
        self.assertGreaterEqual(backend["queue_wait_ms"], 190)
        self.assertEqual((backend["rate_limit_retries"], backend["rate_limit_wait_ms"]), (0, 0.0))
        history = query_api.history_payload({}, result)["generation"]
        self.assertIn("queue_wait_ms", history)

    def test_health_reports_the_queue(self) -> None:
        import backend.main as main_module

        with patch.object(main_module, "check_db_connection", return_value=(True, "connected")):
            body = main_module.health_check()
        queue = body["llm_queue"]
        self.assertEqual(set(queue), {"enabled", "max_wait_seconds", "queue_depth", "estimated_wait_seconds", "models"})
        self.assertIsInstance(queue["queue_depth"], int)


class TestEnvIsolationTests(unittest.TestCase):
    """Step 23: the test runners set LEGALAI_ENV_FILE=none so a developer's .env cannot change test results."""

    def env_file(self, value: str | None) -> str:
        import os
        import subprocess

        env = {key: val for key, val in os.environ.items() if key != "LEGALAI_ENV_FILE"}
        if value is not None:
            env["LEGALAI_ENV_FILE"] = value
        code = "from backend.app.core.config import Settings; print(Settings.model_config['env_file'])"
        return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_none_disables_the_env_file_and_the_default_is_dot_env(self) -> None:
        self.assertEqual(self.env_file("none"), "None")
        self.assertEqual(self.env_file(None), ".env")
        self.assertEqual(self.env_file("custom.env"), "custom.env")


if __name__ == "__main__":
    unittest.main()
