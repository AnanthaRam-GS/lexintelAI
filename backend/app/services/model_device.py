"""Device selection for the local query models (BGE-M3 query embedder, BGE reranker).

``LEGALAI_MODEL_DEVICE`` is ``auto`` (MPS when torch reports it available,
otherwise CPU), ``cpu``, ``mps`` or ``cuda``. A requested accelerator that is
not available resolves to CPU with a warning. If loading or inference fails on
an accelerator, the model is reloaded on CPU with a warning and the call is
retried, so a device problem never fails a query.

Every load and every inference holds the process-wide model lock
(``inference_lock.inference_slot``): two inferences never run at once (step 18).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from backend.app.services.inference_lock import inference_slot

logger = logging.getLogger("legalai.models")

MODEL_DEVICES = ("auto", "cpu", "mps", "cuda")
T = TypeVar("T")


def accelerator_available(device: str, torch_module: Any = None) -> bool:
    if device == "cpu":
        return True
    try:
        torch = torch_module or __import__("torch")
    except ImportError:
        return False
    if device == "mps":
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        return bool(mps is not None and mps.is_available())
    if device == "cuda":
        return bool(torch.cuda.is_available())
    return False


def resolve_model_device(requested: str | None, torch_module: Any = None) -> str:
    """The device to load the query models on: ``cpu``, ``mps`` or ``cuda``."""
    value = (requested or "auto").strip().lower()
    if value not in MODEL_DEVICES:
        logger.warning("model_device_invalid requested=%s using=cpu", value)
        return "cpu"
    if value == "auto":
        return "mps" if accelerator_available("mps", torch_module) else "cpu"
    if not accelerator_available(value, torch_module):
        logger.warning("model_device_unavailable requested=%s using=cpu", value)
        return "cpu"
    return value


def precision_for(device: str, use_fp16: bool) -> str:
    return "fp16" if use_fp16 and device != "cpu" else "fp32"


class DeviceFallbackModel:
    """Holds a FlagEmbedding model on one device, falling back to CPU on failure.

    ``load(device, use_fp16)`` builds the underlying model; ``device`` and
    ``precision`` report what is actually in use.
    """

    def __init__(self, name: str, device: str, use_fp16: bool, load: Callable[[str, bool], Any]) -> None:
        self.name = name
        self._load = load
        self.device = device
        self.use_fp16 = use_fp16 and device != "cpu"
        self.fallback_reason: str | None = None
        with inference_slot(name):  # loading moves weights to the device
            try:
                self.model = load(device, self.use_fp16)
            except Exception as exc:
                if device == "cpu":
                    raise
                self._fall_back(exc, stage="load")

    @property
    def precision(self) -> str:
        return precision_for(self.device, self.use_fp16)

    def run(self, call: Callable[[Any], T]) -> T:
        # The lock is taken before the try: InferenceBusy (a timeout) must not trigger the CPU fallback.
        with inference_slot(self.name):
            try:
                return call(self.model)
            except Exception as exc:
                if self.device == "cpu":
                    raise
                self._fall_back(exc, stage="inference")
                return call(self.model)

    def _fall_back(self, exc: Exception, *, stage: str) -> None:
        logger.warning(
            "model_device_fallback model=%s stage=%s from=%s to=cpu error=%s", self.name, stage, self.device, type(exc).__name__
        )
        self.fallback_reason = f"{stage}:{type(exc).__name__}"
        self.device = "cpu"
        self.use_fp16 = False
        self.model = self._load("cpu", False)
