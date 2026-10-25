"""The process-wide model lock (step 18): no two model calls overlap, waits time out cleanly, warm-up contends correctly.

Fake models only (DeviceFallbackModel with a fake loader), so no model files and no database are needed.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.api import query as query_api  # noqa: E402
from backend.app.services import query_models  # noqa: E402
from backend.app.services.inference_lock import (  # noqa: E402
    MODEL_BUSY_RETRY_AFTER_SECONDS,
    MODELS_LOADING_RETRY_AFTER_SECONDS,
    InferenceBusy,
    inference_status,
    wait_for_inference,
)
from backend.app.services.model_device import DeviceFallbackModel  # noqa: E402
from backend.app.services.private_pdf_rag import _dense_scores  # noqa: E402
from backend.main import app  # noqa: E402
from backend.scripts.tests.test_error_contract import shape_problems  # noqa: E402


class Recorder:
    """Records (start, end, thread) of every fake inference and the largest number running at once."""

    def __init__(self) -> None:
        self.intervals: list[tuple[float, float, str]] = []
        self.running = 0
        self.peak = 0
        self.lock = threading.Lock()

    def model(self, name: str, device: str = "mps", load_seconds: float = 0.0) -> DeviceFallbackModel:
        def load(_device: str, _fp16: bool):
            self.call(load_seconds, f"load:{name}")
            return object()

        return DeviceFallbackModel(name, device, False, load)

    def call(self, seconds: float, label: str) -> str:
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        start = time.perf_counter()
        time.sleep(seconds)
        end = time.perf_counter()
        with self.lock:
            self.running -= 1
            self.intervals.append((start, end, label))
        return label

    def assert_no_overlap(self, test: unittest.TestCase) -> None:
        ordered = sorted(self.intervals)
        for (_s1, end, first), (start, _e2, second) in zip(ordered, ordered[1:]):
            test.assertGreaterEqual(start, end, f"{second} started before {first} ended")
        test.assertEqual(self.peak, 1)


def timeout_env(seconds: float):
    return patch.dict(os.environ, {"LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS": str(seconds)})


class InferenceLockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        query_models._set_status(status="not_loaded")
        self.addCleanup(query_models._set_status, status="not_loaded")
        self.recorder = Recorder()


class NoOverlapTests(InferenceLockTestCase):
    def test_concurrent_calls_on_two_models_never_overlap(self) -> None:
        embedder, reranker = self.recorder.model("bge-m3"), self.recorder.model("bge-reranker")
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                for call in range(3):
                    model = embedder if (index + call) % 2 else reranker
                    model.run(lambda _m, i=index, c=call: self.recorder.call(0.01, f"t{i}c{c}"))
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        with timeout_env(30):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.recorder.intervals), 2 + 12 * 3)  # two loads, 36 inferences
        self.recorder.assert_no_overlap(self)
        self.assertEqual(inference_status(), {"active": 0, "waiting": 0})

    def test_loading_a_model_waits_for_a_running_inference(self) -> None:
        embedder = self.recorder.model("bge-m3")
        started = threading.Event()

        def long_inference() -> None:
            embedder.run(lambda _m: (started.set(), self.recorder.call(0.2, "inference"))[1])

        thread = threading.Thread(target=long_inference)
        thread.start()
        started.wait(5)
        with wait_for_inference():
            self.recorder.model("ingestion-embedder", load_seconds=0.01)  # e.g. an ingestion job loading its embedder
        thread.join()
        self.recorder.assert_no_overlap(self)


class TimeoutTests(InferenceLockTestCase):
    def hold_lock(self, model: DeviceFallbackModel, seconds: float) -> threading.Thread:
        started = threading.Event()
        thread = threading.Thread(target=lambda: model.run(lambda _m: (started.set(), self.recorder.call(seconds, "holder"))[1]))
        thread.start()
        started.wait(5)
        return thread

    def test_a_request_that_waits_too_long_gets_model_busy_without_falling_back_to_cpu(self) -> None:
        loads: list[str] = []
        model = DeviceFallbackModel("bge-m3", "mps", False, lambda device, _fp16: loads.append(device) or object())
        holder = self.hold_lock(model, 0.6)
        with timeout_env(0.1), self.assertRaises(InferenceBusy) as caught:
            model.run(lambda _m: "never runs")
        holder.join()
        busy = caught.exception
        self.assertEqual((busy.code, busy.retry_after), ("MODEL_BUSY", MODEL_BUSY_RETRY_AFTER_SECONDS))
        self.assertGreaterEqual(busy.waited_seconds, 0.1)
        self.assertLess(busy.waited_seconds, 0.5)
        self.assertEqual((model.device, loads), ("mps", ["mps"]))  # no CPU fallback, no reload

    def test_a_request_during_the_warm_up_gets_models_loading(self) -> None:
        model = self.recorder.model("bge-m3")
        query_models._set_status(status="loading")
        holder = self.hold_lock(model, 0.4)
        with timeout_env(0.05), self.assertRaises(InferenceBusy) as caught:
            model.run(lambda _m: "never runs")
        holder.join()
        self.assertEqual((caught.exception.code, caught.exception.retry_after), ("MODELS_LOADING", MODELS_LOADING_RETRY_AFTER_SECONDS))

    def test_background_work_waits_past_the_timeout(self) -> None:
        model = self.recorder.model("bge-m3")
        holder = self.hold_lock(model, 0.3)
        with timeout_env(0.05), wait_for_inference():
            self.assertEqual(model.run(lambda _m: self.recorder.call(0.0, "background")), "background")
        holder.join()
        self.recorder.assert_no_overlap(self)


class FakeService:
    def __init__(self, recorder: Recorder, seconds: float) -> None:
        embedder_runtime = recorder.model("bge-m3")
        reranker_runtime = recorder.model("bge-reranker")
        self.dense_provider = type("E", (), {"embed_query": lambda _s, text: embedder_runtime.run(lambda _m: recorder.call(seconds, f"warm-embed:{text}"))})()
        self.reranker = type("R", (), {"score_texts": lambda _s, q, texts: reranker_runtime.run(lambda _m: recorder.call(seconds, "warm-rerank"))})()
        self.embedder_runtime = embedder_runtime


class WarmUpContentionTests(InferenceLockTestCase):
    def test_a_request_waits_for_the_warm_up_and_health_reports_its_state(self) -> None:
        service = FakeService(self.recorder, 0.15)
        self.assertEqual(query_models.model_status()["warm_up"], "not_started")
        with timeout_env(30):
            warm = query_models.start_warm_up(lambda: service)
            self.assertEqual(query_models.model_status()["warm_up"], "loading")
            result = service.embedder_runtime.run(lambda _m: self.recorder.call(0.01, "request"))  # waits, then runs
            warm.join(10)
        self.assertEqual(result, "request")
        status = query_models.model_status()
        self.assertEqual((status["status"], status["warm_up"]), ("loaded", "ready"))
        self.assertEqual(status["inference"], {"active": 0, "waiting": 0})
        self.recorder.assert_no_overlap(self)
        labels = [label for _s, _e, label in sorted(self.recorder.intervals)]
        self.assertIn("request", labels)
        self.assertTrue({"warm-embed:warm-up query", "warm-rerank"} <= set(labels))

    def test_a_failed_warm_up_is_reported(self) -> None:
        def broken():
            raise RuntimeError("no models")

        query_models.warm_up_query_models(broken)
        self.assertEqual(query_models.model_status()["warm_up"], "failed")


class ApiErrorTests(InferenceLockTestCase):
    def setUp(self) -> None:
        super().setUp()
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: object()
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: object()
        self.addCleanup(app.dependency_overrides.clear)
        env = patch.dict(os.environ, {"APP_ENV": "test"})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app)

    def busy_response(self, code: str, retry_after: int):
        busy = InferenceBusy(code, "message for the user", retry_after, 30.0)
        with patch.object(query_api, "retrieve_legal_evidence", side_effect=busy):
            return self.client.post("/query/public", json={"text": "What is bail?"})

    def test_model_busy_and_models_loading_use_the_unified_shape_with_retry_after(self) -> None:
        for code, retry_after in (("MODEL_BUSY", 15), ("MODELS_LOADING", 10)):
            with self.subTest(code=code):
                response = self.busy_response(code, retry_after)
                self.assertEqual(shape_problems(response), [])
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["retry-after"], str(retry_after))
                self.assertEqual(response.json(), {"error": "message for the user", "code": code, "detail": {"retry_after": retry_after}})

    def test_private_pdf_scoring_reports_busy_instead_of_silently_switching_to_lexical(self) -> None:
        class BusyEmbedder:
            def embed_query(self, _text):
                raise InferenceBusy("MODEL_BUSY", "busy", 15, 30.0)

        with self.assertRaises(InferenceBusy):
            _dense_scores("query", [type("C", (), {"text": "chunk"})()], BusyEmbedder())

        class BrokenEmbedder:
            def embed_query(self, _text):
                raise RuntimeError("model failure")

        self.assertIsNone(_dense_scores("query", [type("C", (), {"text": "chunk"})()], BrokenEmbedder()))  # unchanged


if __name__ == "__main__":
    unittest.main()
