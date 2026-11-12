"""The product's NER backend switch (step E3; docs/experiments/INLEGALBERT_E3_INTEGRATION_DECISION.md).

``LEGALAI_NER_BACKEND``:

- ``deterministic`` (default): ``legal_ner.extract_deterministic_entities``, unchanged.
- ``combined``: the E1 system (docs/experiments/INLEGALBERT_E1_PROTOCOL.md, PASS in INLEGALBERT_E1_RESULTS.md).
  InLegalBERT fine-tuned on InLegalNER (seed 22 checkpoint) predicts InLegalNER's native types, they are mapped to
  ``legalai-ner-schema-v1`` with the frozen E1 mapping, and the deterministic entities are combined with them by the
  product's existing ``merge_hybrid_entities`` (``hybrid`` mode, threshold 0.70). Nothing here is tuned.

The model runs on ``LEGALAI_MODEL_DEVICE`` (MPS when available, CPU otherwise, CPU fallback on failure) in fp32, as
trained. Every load and inference holds the process-wide model lock (``inference_lock``; via ``DeviceFallbackModel``).
Long texts use the E1 windowing: 256-token windows with a stride of 64, batches of 32 windows, and each token labelled
from the window where it is most central.

Any problem with the model (checkpoint missing or with an unexpected hash, load failure, missing dependency, lock
timeout, inference error) falls back to the deterministic entities with a logged warning; ``ner_status()`` reports it
for ``/health``. NER never fails a query.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from backend.app.schemas.legal_ner import CanonicalEntity, EntityProvenance, NERExtractionResult
from backend.app.services.hybrid_legal_ner import HybridMergeConfig, merge_hybrid_entities
from backend.app.services.inference_lock import InferenceBusy, wait_for_inference
from backend.app.services.legal_ner import extract_deterministic_entities

logger = logging.getLogger("legalai.ner")

NER_BACKENDS = ("deterministic", "combined")
DEFAULT_NER_BACKEND = "deterministic"

# E1 seed 22 (the median seed by combined F1); recorded in experiments/inlegalbert/manifest.json.
CHECKPOINT_SHA256 = "427c3fd99c8b98c73b4adc161794e49ef39c852052a28ac6ed7c2d8ec9be0a4c"
CHECKPOINT_WEIGHTS = "model.safetensors"
MODEL_NAME = "law-ai/InLegalBERT+InLegalNER seed 22"
EXTRACTOR = "inlegalbert_e1_ner"
COMBINED_EXTRACTOR = "combined_inlegalbert_e1_ner"

# Frozen E1 recipe and policy.
WINDOW_TOKENS = 256
WINDOW_STRIDE = 64
WINDOW_BATCH = 32
MIN_CONFIDENCE = 0.70
NATIVE_TYPES = ("COURT", "PETITIONER", "RESPONDENT", "JUDGE", "LAWYER", "DATE", "ORG", "GPE", "STATUTE", "PROVISION",
                "PRECEDENT", "CASE_NUMBER", "WITNESS", "OTHER_PERSON")
LABELS = ("O",) + tuple(f"{prefix}-{t}" for t in NATIVE_TYPES for prefix in ("B", "I"))

# Frozen E1 mapping (protocol section 2).
DIRECT_MAP = {"COURT": "COURT", "DATE": "DATE", "STATUTE": "STATUTE", "PROVISION": "SECTION", "ORG": "ORGANIZATION",
              "GPE": "LOCATION", "PRECEDENT": "CASE_NAME", "JUDGE": "PERSON", "LAWYER": "PERSON", "WITNESS": "PERSON",
              "OTHER_PERSON": "PERSON"}
PARTY_TYPES = {"PETITIONER", "RESPONDENT"}
ORG_PARTY_START = re.compile(r"^\s*(?:the\s+)?(?:State|Union of India|Government|Commissioner|Director|Municipal|Central Bureau)\b", re.I)
ORG_PARTY_WORD = re.compile(r"\b(?:Ltd|Limited|Pvt|Bank|Corporation|Company|Department|Board|Authority|Council|Commission|"
                            r"Society|Trust|University|Police)\b", re.I)
WARMUP_TEXT = "The appeal was heard by the High Court of Kerala on 3 March 2024."


def canonical_type(native: str, text: str) -> str | None:
    if native in PARTY_TYPES:
        return "ORGANIZATION" if ORG_PARTY_START.search(text) or ORG_PARTY_WORD.search(text) else "PERSON"
    return DIRECT_MAP.get(native)  # CASE_NUMBER -> None (dropped)


def to_canonical(text: str, raw: list[dict[str, Any]], model_name: str = MODEL_NAME) -> list[CanonicalEntity]:
    """Map raw native-type predictions to canonical entities (all of them; the merge applies the threshold)."""
    entities: list[CanonicalEntity] = []
    seen: set[tuple[int, int, str]] = set()
    for item in raw:
        span = text[item["start"]:item["end"]]
        mapped = canonical_type(item["type"], span)
        if mapped is None or (item["start"], item["end"], mapped) in seen:
            continue
        seen.add((item["start"], item["end"], mapped))
        entities.append(CanonicalEntity(
            text=span, normalized_text=span.casefold(), entity_type=mapped, start_char=item["start"], end_char=item["end"],
            confidence=item["confidence"], source="model", extractor=EXTRACTOR, model_name=model_name,
            metadata={"native_type": item["type"]},
            provenance=[EntityProvenance(source="model", extractor=EXTRACTOR, model_name=model_name, confidence=item["confidence"])]))
    return entities


def combine(text: str, deterministic: list[CanonicalEntity], raw: list[dict[str, Any]]) -> list[CanonicalEntity]:
    """The frozen E1 combination policy: the product's hybrid merge, threshold 0.70."""
    config = HybridMergeConfig(mode="hybrid", min_confidence=MIN_CONFIDENCE)
    return merge_hybrid_entities(deterministic, to_canonical(text, raw), config).entities


def decode_windows(window_offsets: list[list[tuple[int, int]]], window_probs: list[Any]) -> list[dict[str, Any]]:
    """BIO-decode per-window label probabilities into entities (E1 ``predict_entities``).

    ``window_probs[w][t]`` is the probability vector of token ``t`` in window ``w`` (indexable, with ``.max(dim=-1)``
    or a plain list of floats). Each character span takes its label from the window where it is most central.
    """
    best: dict[tuple[int, int], tuple[float, int, float]] = {}
    for offsets, probs in zip(window_offsets, window_probs):
        n = len(offsets)
        for t, (start, end) in enumerate(offsets):
            if start == end:
                continue
            row = probs[t]
            if hasattr(row, "max") and not isinstance(row, list):
                p, label = row.max(dim=-1)
                p, label = float(p), int(label)
            else:
                label = max(range(len(row)), key=row.__getitem__)
                p = float(row[label])
            distance = abs(t - n / 2)
            key = (start, end)
            if key not in best or distance < best[key][0]:
                best[key] = (distance, label, p)
    entities: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for (start, end), (_, label_id, prob) in sorted(best.items()):
        label = LABELS[label_id]
        if label == "O":
            current = None
            continue
        prefix, entity_type = label.split("-", 1)
        if prefix == "I" and current is not None and current["type"] == entity_type:
            current["end"] = end
            current["probs"].append(prob)
            continue
        current = {"start": start, "end": end, "type": entity_type, "probs": [prob]}
        entities.append(current)
    return [{"start": e["start"], "end": e["end"], "type": e["type"],
             "confidence": round(sum(e["probs"]) / len(e["probs"]), 6)} for e in entities]


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class CombinedNerEngine:
    """The seed 22 token classifier behind the process-wide model lock, with the E1 windowing."""

    def __init__(self, checkpoint_dir: Path, device: str) -> None:
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        from backend.app.services.model_device import DeviceFallbackModel

        self.checkpoint_dir = checkpoint_dir
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)

        def load(target: str, _use_fp16: bool) -> Any:
            model = AutoModelForTokenClassification.from_pretrained(checkpoint_dir).to(target)
            model.eval()
            return model

        self.model = DeviceFallbackModel("inlegalbert_ner", device, False, load)  # fp32, as trained
        id2label = {int(k): v for k, v in self.model.model.config.id2label.items()}
        if tuple(id2label[i] for i in range(len(id2label))) != LABELS:
            raise ValueError("checkpoint labels differ from the E1 label set")

    @property
    def device(self) -> str:
        return self.model.device

    def predict(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        enc = self.tokenizer(text, truncation=True, max_length=WINDOW_TOKENS, stride=WINDOW_STRIDE,
                             return_overflowing_tokens=True, return_offsets_mapping=True)
        windows = [(enc["input_ids"][w], enc["attention_mask"][w], [tuple(o) for o in enc["offset_mapping"][w]])
                   for w in range(len(enc["input_ids"]))]
        offsets_all, probs_all = [], []
        for i in range(0, len(windows), WINDOW_BATCH):
            chunk = windows[i:i + WINDOW_BATCH]
            probs = self.model.run(lambda model, chunk=chunk: self._forward(model, chunk))
            for w, (_ids, _mask, offsets) in enumerate(chunk):
                offsets_all.append(offsets)
                probs_all.append(probs[w])
        return decode_windows(offsets_all, probs_all)

    @staticmethod
    def _forward(model: Any, chunk: list[tuple[list[int], list[int], list[tuple[int, int]]]]) -> Any:
        import torch

        device = next(model.parameters()).device
        width = max(len(ids) for ids, _mask, _offsets in chunk)
        input_ids = torch.tensor([ids + [0] * (width - len(ids)) for ids, _m, _o in chunk], device=device)
        attention = torch.tensor([mask + [0] * (width - len(mask)) for _i, mask, _o in chunk], device=device)
        with torch.no_grad():
            return torch.softmax(model(input_ids=input_ids, attention_mask=attention).logits, dim=-1).cpu()


# ---------------------------------------------------------------------------
# Process state
# ---------------------------------------------------------------------------

_engine: Any = None
_engine_lock = threading.Lock()
_state_lock = threading.Lock()
_state: dict[str, Any] = {"status": "not_loaded"}
_counters = {"combined_calls": 0, "fallback_calls": 0}


def _settings() -> Any:
    from backend.app.core.config import Settings

    return Settings()


def configured_backend(settings: Any = None) -> str:
    value = str((settings or _settings()).legalai_ner_backend or DEFAULT_NER_BACKEND).strip().lower()
    if value not in NER_BACKENDS:
        logger.warning("ner_backend_invalid requested=%s using=deterministic", value)
        return DEFAULT_NER_BACKEND
    return value


def checkpoint_dir(settings: Any = None) -> Path:
    from backend.app.core.config import REPO_ROOT

    path = Path((settings or _settings()).legalai_ner_checkpoint_dir)
    return path if path.is_absolute() else REPO_ROOT / path


def _set_state(**values: Any) -> None:
    with _state_lock:
        _state.clear()
        _state.update(values)


def _count(key: str) -> None:
    with _state_lock:
        _counters[key] += 1


def _default_engine_factory(directory: Path, device: str) -> Any:
    return CombinedNerEngine(directory, device)


engine_factory: Callable[[Path, str], Any] = _default_engine_factory


def load_engine(settings: Any = None) -> Any:
    """The combined engine, loaded once; None (with the reason in ``ner_status``) if it cannot be used.

    A lock timeout while loading is not a failure: the call falls back and a later call retries.
    """
    global _engine
    settings = settings or _settings()
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        with _state_lock:
            if _state.get("status") == "failed":
                return None
        directory = checkpoint_dir(settings)
        weights = directory / CHECKPOINT_WEIGHTS
        if not weights.is_file():
            return _fail("checkpoint_missing", f"{weights} not found")
        started = perf_counter()
        try:
            digest = checkpoint_sha256(weights)
        except OSError as exc:
            return _fail("checkpoint_unreadable", type(exc).__name__)
        if digest != CHECKPOINT_SHA256:
            return _fail("checkpoint_hash_mismatch", f"sha256 {digest[:12]}... != {CHECKPOINT_SHA256[:12]}...")
        from backend.app.services.model_device import resolve_model_device

        device = resolve_model_device(settings.legalai_model_device)
        _set_state(status="loading", device=device)
        try:
            engine = engine_factory(directory, device)
        except InferenceBusy:
            _set_state(status="not_loaded")
            raise
        except Exception as exc:  # missing dependency, corrupt files, label mismatch, device failure on CPU
            return _fail("load_failed", type(exc).__name__)
        _engine = engine
        _set_state(status="ready", device=getattr(engine, "device", device),
                   load_ms=round((perf_counter() - started) * 1000, 1), checkpoint_sha256=CHECKPOINT_SHA256)
        logger.info("ner_backend_loaded backend=combined device=%s load_ms=%s", getattr(engine, "device", device),
                    _state.get("load_ms"))
        return _engine


def _fail(reason: str, detail: str) -> None:
    logger.warning("ner_backend_fallback backend=combined using=deterministic reason=%s detail=%s", reason, detail)
    _set_state(status="failed", reason=reason)
    return None


def reset_ner_backend() -> None:
    """Forget the loaded engine and state (tests, or after replacing the checkpoint)."""
    global _engine
    with _engine_lock:
        _engine = None
    _set_state(status="not_loaded")
    with _state_lock:
        _counters.update(combined_calls=0, fallback_calls=0)


def extract_entities(text: str, settings: Any = None) -> NERExtractionResult:
    """Entities from the configured backend. ``deterministic`` returns the rule-based result unchanged."""
    return extract_entities_detailed(text, settings)[0]


def extract_entities_detailed(text: str, settings: Any = None) -> tuple[NERExtractionResult, list[CanonicalEntity]]:
    """(the configured backend's entities, the model's own entities) from one inference.

    The second list holds the model's predictions mapped with the frozen E1 mapping and kept at the frozen E1
    threshold (confidence >= 0.70), before the hybrid merge, each with its InLegalNER type in
    ``metadata["native_type"]`` (step E4 party roles: the merge can drop that type when a rule entity has the same
    span). It is empty with ``deterministic`` and whenever the model falls back.
    """
    deterministic = extract_deterministic_entities(text)
    settings = settings or _settings()
    if configured_backend(settings) != "combined":
        return deterministic, []
    started = perf_counter()
    try:
        engine = load_engine(settings)
        raw = engine.predict(text) if engine is not None else None
    except InferenceBusy as exc:
        logger.warning("ner_backend_fallback backend=combined using=deterministic reason=lock_timeout code=%s", exc.code)
        raw = None
    except Exception as exc:  # an inference error must not fail the query
        logger.warning("ner_backend_fallback backend=combined using=deterministic reason=inference_error error=%s",
                       type(exc).__name__)
        raw = None
    if raw is None:
        _count("fallback_calls")
        return deterministic, []
    entities = combine(text, deterministic.entities, raw)
    _count("combined_calls")
    model_entities = [entity for entity in to_canonical(text, raw) if entity.confidence >= MIN_CONFIDENCE]
    return NERExtractionResult(
        text=text,
        entities=entities,
        extractor=COMBINED_EXTRACTOR,
        model_name=MODEL_NAME,
        latency_ms=round(deterministic.latency_ms + (perf_counter() - started) * 1000, 3),
        entity_count=len(entities),
    ), model_entities


def with_backend_entities(understanding: Any, settings: Any = None) -> Any:
    """A copy of a ``LegalQueryUnderstanding`` whose entities come from the configured backend.

    ``legal_query_understanding.py`` is hash-pinned and always uses the deterministic NER, so the query API applies
    the backend here. Unchanged (the same object) with the deterministic backend.
    """
    settings = settings or _settings()
    if configured_backend(settings) == "deterministic":
        return understanding
    result = extract_entities(understanding.query, settings)
    entities = sorted(result.entities, key=lambda item: (item.start_char, item.end_char, item.entity_type))
    return understanding.model_copy(update={"entities": entities})


def warm_up_ner(settings: Any = None) -> dict[str, Any]:
    """Load the combined engine and run one tiny inference (startup, background thread). No-op if deterministic."""
    settings = settings or _settings()
    if configured_backend(settings) != "combined":
        return ner_status(settings)
    try:
        with wait_for_inference():  # background work: wait for the model lock without a limit
            engine = load_engine(settings)
            if engine is not None:
                started = perf_counter()
                engine.predict(WARMUP_TEXT)
                with _state_lock:
                    _state["warmup_ms"] = round((perf_counter() - started) * 1000, 1)
    except Exception as exc:  # never block startup
        _fail("warmup_failed", type(exc).__name__)
    return ner_status(settings)


def start_ner_warm_up(settings: Any = None) -> threading.Thread | None:
    settings = settings or _settings()
    if configured_backend(settings) != "combined":
        return None
    thread = threading.Thread(target=warm_up_ner, args=(settings,), name="legalai-ner-warmup", daemon=True)
    thread.start()
    return thread


def ner_status(settings: Any = None) -> dict[str, Any]:
    """For /health: requested and active backend, model state and fallback counts (no text, no paths)."""
    settings = settings or _settings()
    requested = configured_backend(settings)
    with _state_lock:
        state = dict(_state)
        counters = dict(_counters)
    if requested != "combined":
        return {"backend": requested, "active": "deterministic", "model": "not_used"}
    active = "combined" if state.get("status") in {"ready", "not_loaded", "loading"} else "deterministic"
    return {"backend": requested, "active": active, "model": state, "calls": counters,
            "fallback": state.get("status") == "failed"}
