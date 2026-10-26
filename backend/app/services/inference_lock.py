"""One process-wide lock for every local model call (step 18).

The query embedder, the reranker, the ingestion embedder and the startup warm-up share one PyTorch runtime. On
Apple MPS, two inferences at once crash the process with a segmentation fault (step 17/18: reproduced in 10 of 10
starts with warm-up and 10 concurrent queries, and in 3 of 3 with concurrent queries alone). So every model load and
every inference holds this lock (``DeviceFallbackModel``), on every device:

- MPS: required; concurrent use is not safe.
- CPU: PyTorch already spreads one inference over all cores, so concurrent inferences only compete for them. Measured
  with 10 concurrent queries, serialising cut the median latency (docs/performance/PERFORMANCE_BASELINE.md).

Waiting: request threads wait at most ``LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS`` (default 30) and then get
``InferenceBusy``, answered as ``MODELS_LOADING`` while the warm-up runs and ``MODEL_BUSY`` otherwise, both with
``Retry-After``. The warm-up and ingestion (background work) wait without a limit (``wait_for_inference``).

The lock is reentrant, so a CPU fallback that reloads a model inside an inference does not deadlock.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
from collections.abc import Iterator
from time import perf_counter

logger = logging.getLogger("legalai.models")

MODEL_BUSY_RETRY_AFTER_SECONDS = 15
MODELS_LOADING_RETRY_AFTER_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 30.0

_lock = threading.RLock()
_unbounded = contextvars.ContextVar("legalai_inference_unbounded_wait", default=False)
_stats_lock = threading.Lock()
_active = 0
_waiting = 0


class InferenceBusy(Exception):
    """A request could not get the model in time. Not a RuntimeError: retrieval treats those as missing stores."""

    def __init__(self, code: str, message: str, retry_after: int, waited_seconds: float) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.waited_seconds = waited_seconds


def lock_timeout_seconds() -> float:
    from backend.app.core.config import Settings

    value = Settings().legalai_inference_lock_timeout_seconds
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


@contextlib.contextmanager
def wait_for_inference() -> Iterator[None]:
    """Model calls in this block wait for the lock without a time limit (warm-up, ingestion)."""
    token = _unbounded.set(True)
    try:
        yield
    finally:
        _unbounded.reset(token)


def _busy(waited: float) -> InferenceBusy:
    from backend.app.services.query_models import warm_up_in_progress

    if warm_up_in_progress():
        return InferenceBusy(
            "MODELS_LOADING",
            "The legal search is still starting up. Please try again in a few seconds.",
            MODELS_LOADING_RETRY_AFTER_SECONDS,
            waited,
        )
    return InferenceBusy(
        "MODEL_BUSY",
        "Many people are asking questions right now. Please try again in a moment.",
        MODEL_BUSY_RETRY_AFTER_SECONDS,
        waited,
    )


@contextlib.contextmanager
def inference_slot(name: str) -> Iterator[None]:
    """Hold the process-wide model lock for one load or inference of ``name``."""
    global _active, _waiting
    timeout = -1 if _unbounded.get() else lock_timeout_seconds()
    started = perf_counter()
    with _stats_lock:
        _waiting += 1
    try:
        acquired = _lock.acquire(timeout=timeout)
    finally:
        with _stats_lock:
            _waiting -= 1
    waited = perf_counter() - started
    if not acquired:
        busy = _busy(waited)
        logger.warning("inference_lock_timeout model=%s waited_s=%.1f code=%s", name, waited, busy.code)
        raise busy
    if waited > 0.1:
        logger.info("inference_lock_wait model=%s waited_ms=%.0f", name, waited * 1000)
    with _stats_lock:
        _active += 1
    try:
        yield
    finally:
        with _stats_lock:
            _active -= 1
        _lock.release()


def inference_status() -> dict[str, int]:
    """For /health: calls holding the lock (0 or 1, plus reentrant holds) and calls waiting for it."""
    with _stats_lock:
        return {"active": _active, "waiting": _waiting}
