"""Load-once query models (BGE-M3 query embedder, BGE reranker), warm-up and load status.

The models are cached by configuration, separately from the retrieval service,
so rebuilding the service after an ingestion update reuses the loaded models.
At startup ``warm_up_query_models`` loads them and runs one tiny inference, so
the first query's stage timings contain no model load. ``model_status`` reports
the state for ``/health``: ``warm_up`` is ``loading``, ``ready``, ``failed`` or
``not_started`` (warm-up disabled), and ``inference`` counts the calls holding and
waiting for the process-wide model lock (``inference_lock.py``). The warm-up's own
model calls wait for that lock without a time limit; a query that cannot get it in
time during the warm-up is answered ``MODELS_LOADING``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from time import perf_counter
from typing import Any, Callable

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.inference_lock import inference_status, wait_for_inference
from backend.app.services.reranking.base import RerankerConfig

logger = logging.getLogger("legalai.models")

WARMUP_QUERY = "warm-up query"
WARMUP_PASSAGE = "warm-up passage"


@dataclass(frozen=True)
class QueryModels:
    dense_provider: Any
    reranker: Any


_models: dict[tuple[EmbeddingConfig, RerankerConfig], QueryModels] = {}
_models_lock = threading.Lock()
_status_lock = threading.Lock()
_status: dict[str, Any] = {"status": "not_loaded"}
_active: QueryModels | None = None


def load_query_models(embedding_config: EmbeddingConfig, reranker_config: RerankerConfig) -> QueryModels:
    """The embedder and reranker for these configs, loaded once per process."""
    global _active
    key = (embedding_config, reranker_config)
    with _models_lock:
        if key not in _models:
            from backend.app.services.embeddings.bge_m3 import BgeM3EmbeddingProvider
            from backend.app.services.reranking.bge import BgeReranker

            started = perf_counter()
            models = QueryModels(BgeM3EmbeddingProvider(embedding_config), BgeReranker(reranker_config))
            logger.info(
                "query_models_loaded device=%s precision=%s load_ms=%.1f",
                embedding_config.device,
                "fp16" if embedding_config.use_fp16 and embedding_config.device != "cpu" else "fp32",
                (perf_counter() - started) * 1000,
            )
            _models[key] = models
        _active = _models[key]
        return _active


def clear_query_models() -> None:
    global _active
    with _models_lock:
        _models.clear()
        _active = None
    _set_status(status="not_loaded")


def active_model_device() -> dict[str, str] | None:
    """Device and precision of the loaded query models (after any CPU fallback), or None."""
    models = _active
    if models is None:
        return None
    return {
        "embedder": f"{getattr(models.dense_provider, 'device', 'unknown')}/{getattr(models.dense_provider, 'precision', 'unknown')}",
        "reranker": f"{getattr(models.reranker, 'device', 'unknown')}/{getattr(models.reranker, 'precision', 'unknown')}",
    }


def _set_status(**values: Any) -> None:
    global _status
    with _status_lock:
        _status = values


WARM_UP_STATES = {"loading": "loading", "loaded": "ready", "failed": "failed"}


def warm_up_in_progress() -> bool:
    with _status_lock:
        return _status.get("status") == "loading"


def model_status() -> dict[str, Any]:
    with _status_lock:
        status = dict(_status)
    status["warm_up"] = WARM_UP_STATES.get(status["status"], "not_started")
    devices = active_model_device()
    if devices is not None:
        status["devices"] = devices
        if status["status"] == "not_loaded":  # loaded on demand by a query (warm-up disabled)
            status["status"] = "loaded"
    status["inference"] = inference_status()
    return status


def warm_up_query_models(get_service: Callable[[], Any]) -> dict[str, Any]:
    """Load the retrieval service (and its models), then run one tiny embed and rerank."""
    _set_status(status="loading")
    try:
        with wait_for_inference():  # background work: wait for the model lock without a limit
            started = perf_counter()
            service = get_service()
            load_ms = round((perf_counter() - started) * 1000, 1)
            started = perf_counter()
            service.dense_provider.embed_query(WARMUP_QUERY)
            score_texts = getattr(service.reranker, "score_texts", None)
            if score_texts is not None:
                score_texts(WARMUP_QUERY, [WARMUP_PASSAGE])
            warmup_ms = round((perf_counter() - started) * 1000, 1)
    except Exception as exc:  # never block startup; queries load the models on demand
        logger.error("query_models_warmup_failed error=%s", type(exc).__name__)
        _set_status(status="failed", error=type(exc).__name__)
        return model_status()
    _set_status(status="loaded", load_ms=load_ms, warmup_ms=warmup_ms)
    logger.info("query_models_warmup status=loaded devices=%s load_ms=%s warmup_ms=%s", active_model_device(), load_ms, warmup_ms)
    return model_status()


def start_warm_up(get_service: Callable[[], Any]) -> threading.Thread:
    """Warm up in a background thread so the server starts answering /health at once."""
    _set_status(status="loading")
    thread = threading.Thread(target=warm_up_query_models, args=(get_service,), name="legalai-model-warmup", daemon=True)
    thread.start()
    return thread
