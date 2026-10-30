"""Daily token and request budgets per LLM model, over a rolling 24-hour window (steps 24b-24c), persisted.

Groq's free tier allows 200,000 tokens per model per day (HTTP 429 "Rate limit reached for model … on tokens per
day (TPD): Limit 200000"), and sends no header for it. Its window is **rolling**: in step 24 its retry times were
minutes in mid-afternoon, which a reset at 00:00 UTC could not produce. The per-minute pacing (``llm_pacing.py``)
cannot see that limit, so a day of heavy use ended in 429s and ``MODEL_BUSY``. This module:

- **Records** each answered request's provider-reported tokens (prompt + completion) with its timestamp, per model,
  in a small JSON file (``LEGALAI_LLM_DAILY_USAGE_FILE``, default ``data/runtime/llm_daily_usage.json``,
  gitignored). Writes are atomic (temporary file + rename), so the record survives a restart. Entries older than
  the window are dropped.
- **Checks before sending:** a model's remaining budget is its limit (``LEGALAI_GROQ_TOKENS_PER_DAY``, default
  200,000; optional ``LEGALAI_GROQ_REQUESTS_PER_DAY``) minus its usage in the last 24 hours. A model whose remaining
  budget cannot hold the request's estimate, or that is marked exhausted, is skipped. The provider chain then tries
  the fallback allowed for the mode. When nothing can serve, the API answers ``503 DAILY_CAPACITY_REACHED`` with
  ``Retry-After`` = the time until enough usage ages out of the window to fit the request.
- **Marks a model exhausted** when the provider reports its daily limit anyway (usage from before the record
  started, or another client on the same account): until the provider's ``retry-after`` when given, otherwise until
  the oldest recorded usage ages out (or an hour, when none is recorded).

Only usage numbers and timestamps are stored: no prompts, answers, keys or user data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("legalai.llm_daily_quota")

Key = tuple[str, str]  # (rate-limit account, model)
WINDOW_SECONDS = 24 * 3600
WINDOW_NAME = "rolling_24h"
# A provider daily-limit error without a retry time, and no recorded usage to age out: try again in an hour.
UNKNOWN_EXHAUSTION_SECONDS = 3600.0
DAILY_LIMIT_MESSAGE = re.compile(r"(tokens|requests) per day|\b(TPD|RPD)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DailyLimits:
    tokens_per_day: int
    requests_per_day: int | None = None


class DailyCapacityReached(Exception):
    """No model allowed for this request has capacity left in its rolling window; answered 503 DAILY_CAPACITY_REACHED."""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("the answer models' 24-hour capacity is used up")
        self.retry_after_seconds = max(1, int(round(retry_after_seconds)))


def is_daily_limit_error(exc: Exception) -> bool:
    """A provider 429 that names a per-day limit (Groq: "tokens per day (TPD)")."""
    text = " ".join(str(part) for part in (getattr(exc, "provider_message", None), getattr(exc, "provider_code", None), exc) if part)
    return getattr(exc, "http_status", None) == 429 and bool(DAILY_LIMIT_MESSAGE.search(text))


class DailyQuota:
    """Per-model usage over a rolling window, with limits; thread-safe; persisted to ``path`` (None: in memory)."""

    def __init__(self, path: Path | None, *, clock: Callable[[], float] = time.time, window_seconds: float = WINDOW_SECONDS) -> None:
        self.path = Path(path) if path else None
        self._clock = clock
        self.window_seconds = float(window_seconds)
        self._lock = threading.Lock()
        self._limits: dict[Key, DailyLimits] = {}
        self._state = self._load()

    # -- persistence ----------------------------------------------------------------------------------------------

    def _empty(self) -> dict[str, Any]:
        return {"window": WINDOW_NAME, "models": {}}

    def _load(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return self._empty()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("window") != WINDOW_NAME or not isinstance(state.get("models"), dict):
                raise ValueError("not a rolling-window usage file")
            for entry in state["models"].values():
                entry["events"] = [[float(at), int(tokens)] for at, tokens in entry.get("events", [])]
            return state
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("daily usage file unreadable, starting a new record: %s", type(exc).__name__)
            return self._empty()

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".llm_daily_usage.", dir=self.path.parent)
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(self._state, file, indent=1, sort_keys=True)
        os.replace(temporary, self.path)

    def _entry(self, key: Key, now: float) -> dict[str, Any]:
        """The model's entry, with usage older than the window dropped."""
        entry = self._state["models"].setdefault(f"{key[0]}/{key[1]}", {"events": [], "exhausted_until": None})
        cutoff = now - self.window_seconds
        entry["events"] = [event for event in entry["events"] if event[0] > cutoff]
        return entry

    # -- configuration -----------------------------------------------------------------------------------------------

    def configure(self, key: Key, limits: DailyLimits) -> None:
        with self._lock:
            self._limits[key] = limits

    def is_tracked(self, key: Key) -> bool:
        with self._lock:
            return key in self._limits

    # -- checks and accounting --------------------------------------------------------------------------------------

    def can_serve(self, key: Key, estimated_tokens: int) -> bool:
        """True when ``key`` is untracked, or its last 24 hours leave room for the request and it is not exhausted."""
        return self.seconds_until_fits(key, estimated_tokens) == 0.0

    def seconds_until_fits(self, key: Key, estimated_tokens: int) -> float:
        """0 when ``key`` can take the request now; otherwise the time until enough usage ages out of the window (and
        any exhaustion mark has passed) for it to fit."""
        with self._lock:
            limits = self._limits.get(key)
            if limits is None:
                return 0.0
            now = self._clock()
            entry = self._entry(key, now)
            waits = [max(0.0, (entry.get("exhausted_until") or 0) - now)]
            events = entry["events"]
            # Tokens: drop the oldest usage until the rest plus the request fits (a request larger than the whole
            # limit fits only in an empty window).
            needed = min(max(0, estimated_tokens), limits.tokens_per_day)
            used = sum(tokens for _at, tokens in events)
            for at, tokens in events:
                if used + needed <= limits.tokens_per_day:
                    break
                used -= tokens
                waits.append(at + self.window_seconds - now)
            # Requests: the oldest request has to age out once the count is at its limit.
            if limits.requests_per_day is not None and len(events) >= limits.requests_per_day:
                index = len(events) - limits.requests_per_day
                waits.append(events[index][0] + self.window_seconds - now)
            return max(waits)

    def seconds_until_available(self, key: Key, estimated_tokens: int = 1) -> float:
        """When ``key`` can take a request of ``estimated_tokens`` (for ``Retry-After``)."""
        return self.seconds_until_fits(key, estimated_tokens)

    def record(self, key: Key, tokens: int | None, *, requests: int = 1) -> None:
        """Add one answered request's provider-reported tokens (prompt + completion), timestamped now."""
        with self._lock:
            if key not in self._limits:
                return
            now = self._clock()
            entry = self._entry(key, now)
            entry["events"].append([now, max(0, int(tokens or 0))])
            for _ in range(max(0, requests - 1)):
                entry["events"].append([now, 0])
            self._save()

    def mark_exhausted(self, key: Key, retry_after_seconds: float | None) -> None:
        """The provider reported the daily limit: no requests to ``key`` until its retry time (else until the oldest
        recorded usage ages out, or an hour when none is recorded)."""
        with self._lock:
            now = self._clock()
            entry = self._entry(key, now)
            if retry_after_seconds:
                seconds = float(retry_after_seconds)
            elif entry["events"]:
                seconds = entry["events"][0][0] + self.window_seconds - now
            else:
                seconds = UNKNOWN_EXHAUSTION_SECONDS
            entry["exhausted_until"] = max(entry.get("exhausted_until") or 0, now + seconds)
            self._save()
            logger.warning("daily_limit model=%s/%s exhausted_for_s=%.0f", key[0], key[1], seconds)

    # -- /health --------------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            models = {}
            for key, limits in sorted(self._limits.items()):
                entry = self._entry(key, now)
                used = sum(tokens for _at, tokens in entry["events"])
                until = entry.get("exhausted_until") or 0
                models[f"{key[0]}/{key[1]}"] = {
                    "tokens_used": used,
                    "tokens_per_day": limits.tokens_per_day,
                    "tokens_remaining": max(0, limits.tokens_per_day - used),
                    "requests_used": len(entry["events"]),
                    "requests_per_day": limits.requests_per_day,
                    "exhausted_for_seconds": round(until - now) if until > now else 0,
                    # When the oldest usage in the window ages out (frees its tokens); None when nothing is used.
                    "oldest_usage_expires_in_seconds": round(entry["events"][0][0] + self.window_seconds - now) if entry["events"] else None,
                }
            return {"window": WINDOW_NAME, "window_seconds": int(self.window_seconds), "models": models}


_DEFAULT: DailyQuota | None = None
_DEFAULT_LOCK = threading.Lock()


def daily_quota(settings: Any = None) -> DailyQuota:
    """The process-wide quota, persisted at LEGALAI_LLM_DAILY_USAGE_FILE (relative paths from the repository root)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            from backend.app.core.config import REPO_ROOT, Settings

            raw = (settings or Settings()).legalai_llm_daily_usage_file
            path = None if not raw or raw.lower() == "none" else Path(raw)
            if path is not None and not path.is_absolute():
                path = REPO_ROOT / path
            _DEFAULT = DailyQuota(path)
        return _DEFAULT


def reset_default_quota(quota: DailyQuota | None = None) -> None:
    """Tests: replace (or clear) the process-wide quota."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = quota
