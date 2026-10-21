"""Query-model device selection, CPU fallback, warm-up, /health status and BE-004 (no models, no network, no database)."""

from __future__ import annotations

import asyncio
import sys
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from backend.app.api import query as query_api
from backend.app.core.config import Settings
from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.db.session import get_db
from backend.app.services import query_models
from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.model_device import DeviceFallbackModel, precision_for, resolve_model_device
from backend.app.services.reranking.base import RerankerConfig
from backend.main import app


def fake_torch(*, mps: bool, cuda: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        cuda=SimpleNamespace(is_available=lambda: cuda),
    )


class DeviceResolutionTests(unittest.TestCase):
    def test_auto_uses_mps_when_available_else_cpu(self) -> None:
        self.assertEqual(resolve_model_device("auto", fake_torch(mps=True)), "mps")
        self.assertEqual(resolve_model_device("auto", fake_torch(mps=False)), "cpu")
        self.assertEqual(resolve_model_device(None, fake_torch(mps=True)), "mps")

    def test_forced_cpu_is_honoured_even_with_mps(self) -> None:
        self.assertEqual(resolve_model_device("cpu", fake_torch(mps=True)), "cpu")

    def test_unavailable_or_invalid_device_resolves_to_cpu_with_a_warning(self) -> None:
        with self.assertLogs("legalai.models", "WARNING") as logs:
            self.assertEqual(resolve_model_device("mps", fake_torch(mps=False)), "cpu")
            self.assertEqual(resolve_model_device("cuda", fake_torch(mps=True, cuda=False)), "cpu")
            self.assertEqual(resolve_model_device("tpu", fake_torch(mps=True)), "cpu")
        self.assertEqual(len(logs.records), 3)
        self.assertEqual(resolve_model_device("cuda", fake_torch(mps=False, cuda=True)), "cuda")

    def test_settings_default_is_auto_with_fp16_reranker_and_warmup(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual(settings.legalai_model_device, "auto")
        self.assertTrue(settings.legalai_reranker_fp16)
        self.assertTrue(settings.legalai_model_warmup)

    def test_fp16_applies_only_off_cpu(self) -> None:
        self.assertEqual(precision_for("cpu", True), "fp32")
        self.assertEqual(precision_for("mps", True), "fp16")
        self.assertEqual(precision_for("mps", False), "fp32")


class FakeModel:
    def __init__(self, device: str, fail: bool = False) -> None:
        self.device = device
        self.fail = fail
        self.calls = 0

    def score(self) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("MPS backend out of memory")
        return self.device


class DeviceFallbackTests(unittest.TestCase):
    def test_inference_failure_on_mps_reloads_on_cpu_and_retries(self) -> None:
        loads = []

        def load(device: str, use_fp16: bool) -> FakeModel:
            loads.append((device, use_fp16))
            return FakeModel(device, fail=device == "mps")

        runtime = DeviceFallbackModel("reranker", "mps", True, load)
        self.assertEqual(runtime.precision, "fp16")
        with self.assertLogs("legalai.models", "WARNING") as logs:
            self.assertEqual(runtime.run(lambda model: model.score()), "cpu")
        self.assertEqual(loads, [("mps", True), ("cpu", False)])
        self.assertEqual((runtime.device, runtime.precision, runtime.fallback_reason), ("cpu", "fp32", "inference:RuntimeError"))
        self.assertIn("model_device_fallback model=reranker stage=inference from=mps to=cpu", logs.output[0])
        self.assertEqual(runtime.run(lambda model: model.score()), "cpu")  # stays on CPU, no reload
        self.assertEqual(len(loads), 2)

    def test_load_failure_on_mps_falls_back_to_cpu(self) -> None:
        def load(device: str, use_fp16: bool) -> FakeModel:
            if device == "mps":
                raise RuntimeError("mps unavailable")
            return FakeModel(device)

        with self.assertLogs("legalai.models", "WARNING"):
            runtime = DeviceFallbackModel("bge-m3", "mps", False, load)
        self.assertEqual((runtime.device, runtime.fallback_reason), ("cpu", "load:RuntimeError"))

    def test_cpu_failure_is_raised(self) -> None:
        runtime = DeviceFallbackModel("bge-m3", "cpu", False, lambda device, fp16: FakeModel(device, fail=True))
        with self.assertRaises(RuntimeError):
            runtime.run(lambda model: model.score())


class FakeFlagModule(types.ModuleType):
    """Stand-in for FlagEmbedding that records constructor arguments."""

    def __init__(self) -> None:
        super().__init__("FlagEmbedding")
        self.created: list[tuple[str, dict]] = []
        module = self

        class BGEM3FlagModel:
            def __init__(self, path, **kwargs) -> None:
                module.created.append(("embedder", kwargs))

            def encode(self, texts, **kwargs):
                import numpy

                return {"dense_vecs": numpy.ones((len(texts), 4))}

        class FlagReranker:
            def __init__(self, path, **kwargs) -> None:
                module.created.append(("reranker", kwargs))

            def compute_score(self, pairs, **kwargs):
                return [float(len(text)) for _query, text in pairs]

        self.BGEM3FlagModel = BGEM3FlagModel
        self.FlagReranker = FlagReranker


class ModelConstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flag = FakeFlagModule()
        patcher = patch.dict(sys.modules, {"FlagEmbedding": self.flag})
        patcher.start()
        self.addCleanup(patcher.stop)
        query_models.clear_query_models()
        self.addCleanup(query_models.clear_query_models)

    def test_device_is_passed_as_devices_to_flagembedding(self) -> None:
        # FlagEmbedding ignores ``device=`` and auto-selects an accelerator; the device must go in ``devices``.
        from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
        from backend.app.services.reranking.bge import BgeReranker

        BgeM3EmbeddingProvider(EmbeddingConfig(device="cpu"))
        BgeReranker(RerankerConfig(device="mps", use_fp16=True))
        self.assertEqual(self.flag.created[0][1]["devices"], "cpu")
        self.assertNotIn("device", self.flag.created[0][1])
        self.assertEqual((self.flag.created[1][1]["devices"], self.flag.created[1][1]["use_fp16"]), ("mps", True))

    def test_models_are_loaded_once_per_config_and_reported(self) -> None:
        embedding, reranker = EmbeddingConfig(device="mps"), RerankerConfig(device="mps")
        first = query_models.load_query_models(embedding, reranker)
        self.assertIs(query_models.load_query_models(embedding, reranker), first)
        self.assertEqual(len(self.flag.created), 2)
        self.assertEqual(query_models.active_model_device(), {"embedder": "mps/fp32", "reranker": "mps/fp32"})
        self.assertEqual(first.reranker.score_texts("q", ["ab", "abcd"]), [2.0, 4.0])

    def test_warm_up_loads_once_and_runs_one_tiny_inference(self) -> None:
        calls = []
        models = query_models.load_query_models(EmbeddingConfig(device="cpu"), RerankerConfig(device="cpu"))
        service = SimpleNamespace(dense_provider=models.dense_provider, reranker=models.reranker)
        with patch.object(models.reranker, "score_texts", side_effect=lambda q, texts: calls.append((q, texts)) or [0.0]):
            status = query_models.warm_up_query_models(lambda: service)
        self.assertEqual(status["status"], "loaded")
        self.assertEqual(status["devices"], {"embedder": "cpu/fp32", "reranker": "cpu/fp32"})
        self.assertEqual(calls, [(query_models.WARMUP_QUERY, [query_models.WARMUP_PASSAGE])])
        self.assertIn("load_ms", status)
        self.assertIn("warmup_ms", status)

    def test_warm_up_failure_is_reported_and_does_not_raise(self) -> None:
        def unavailable():
            raise RuntimeError("index missing")

        with self.assertLogs("legalai.models", "ERROR"):
            status = query_models.warm_up_query_models(unavailable)
        self.assertEqual(status, {"status": "failed", "error": "RuntimeError"})


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        query_models.clear_query_models()
        self.addCleanup(query_models.clear_query_models)

    def health(self) -> dict:
        async def call() -> dict:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return (await client.get("/health")).json()

        with patch("backend.main.check_db_connection", return_value=(True, "connected")):
            return asyncio.run(call())

    def test_health_reports_model_loading_state(self) -> None:
        self.assertEqual(self.health()["models"], {"status": "not_loaded"})
        query_models._set_status(status="loading")
        self.assertEqual(self.health()["models"], {"status": "loading"})
        query_models._set_status(status="loaded", load_ms=1.0, warmup_ms=2.0)
        self.assertEqual(self.health()["models"]["status"], "loaded")


QUERY_SECONDS = 1.0


class NonBlockingQueryTests(unittest.TestCase):
    """BE-004: a slow PDF query must not stop /health from answering meanwhile."""

    def setUp(self) -> None:
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: SimpleNamespace(dense_provider=None)
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: object()
        app.dependency_overrides[get_db] = lambda: None
        app.dependency_overrides[require_lawyer_or_admin] = lambda: SimpleNamespace(id=1, role="lawyer")
        self.addCleanup(app.dependency_overrides.clear)

    def slow_pipeline(self, *args, **kwargs):
        time.sleep(QUERY_SECONDS)  # blocking, as real reranking and provider calls are
        raise query_api.QueryExecutionError("MODEL_PROVIDER_UNAVAILABLE", "slow mocked provider", 503)

    def slow_parse(self, path, name):
        time.sleep(QUERY_SECONDS / 2)  # blocking, as real PDF parsing is
        return {"text": "", "page_count": 1}, []

    def run_concurrently(self, endpoint: str, form: dict) -> tuple[float, float, int]:
        async def scenario() -> tuple[float, float, int]:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=30) as client:
                started = time.perf_counter()
                query = asyncio.create_task(
                    client.post(endpoint, data=form, files={"file": ("fir.pdf", b"%PDF-1.4 mocked", "application/pdf")})
                )
                await asyncio.sleep(0.2)
                health = await client.get("/health")
                health_done = time.perf_counter() - started
                self.assertEqual(health.status_code, 200)
                response = await query
                return health_done, time.perf_counter() - started, response.status_code

        with (
            patch.object(query_api, "parse_and_chunk_pdf", side_effect=self.slow_parse),
            patch.object(query_api, "run_frozen_query_pipeline", side_effect=self.slow_pipeline),
            patch.object(query_api, "build_document_map_or_fail", return_value=object()),
            patch("backend.main.check_db_connection", return_value=(True, "connected")),
        ):
            return asyncio.run(scenario())

    def assert_not_blocked(self, endpoint: str, form: dict) -> None:
        health_done, query_done, status_code = self.run_concurrently(endpoint, form)
        self.assertEqual(status_code, 503)
        self.assertGreaterEqual(query_done, QUERY_SECONDS * 1.5)
        # /health answered while the query was still parsing/answering, not after it.
        self.assertLess(health_done, QUERY_SECONDS / 2)

    def test_public_pdf_query_does_not_block_health(self) -> None:
        self.assert_not_blocked("/query/public/pdf", {"query": "What does this FIR allege?"})

    def test_professional_pdf_query_does_not_block_health(self) -> None:
        self.assert_not_blocked("/query/professional/pdf", {"query": "Who is the accused?", "analysis_mode": "question"})


if __name__ == "__main__":
    unittest.main()
