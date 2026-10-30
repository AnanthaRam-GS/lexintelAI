"""Daily token and request budgets per LLM model (step 24b), persisted across restarts.

Groq's free tier allows 200,000 tokens per model per day (observed: HTTP 429 "Rate limit reached for model … on
tokens per day (TPD): Limit 200000"), and sends no header for it. The per-minute pacing (``llm_pacing.py``)
cannot see that limit, so a day of heavy use ended in 429s and ``MODEL_BUSY`` (step 24). This module:

- **Counts** each model's provider-reported tokens (prompt + completion) and requests per UTC day, in a small JSON
  file (``LEGALAI_LLM_DAILY_USAGE_FILE``, default ``data/runtime/llm_daily_usage.json``, gitignored). Writes are
  atomic (temporary file + rename), so the count survives a restart.
- **Checks before sending:** a model whose used tokens plus the request's estimate would exceed its daily limit
  (``LEGALAI_GROQ_TOKENS_PER_DAY``, default 200,000; optional ``LEGALAI_GROQ_REQUESTS_PER_DAY``), or that is marked
  exhausted, is skipped. The provider chain then tries the fallback allowed for the mode; when nothing can serve, the
  API answers ``503 DAILY_CAPACITY_REACHED`` with ``Retry-After`` = the seconds until capacity returns.
- **Marks a model exhausted** when the provider reports its daily limit anyway (the count started late, or another
  client shares the account): until the provider's ``retry-after`` when given, otherwise until the UTC reset.

Groq's daily window behaves like a rolling 24 hours (step 24: retry times of minutes in mid-afternoon), while this
count resets at 00:00 UTC. The count is therefore an approximation, and the exhaustion marking from the provider's
own error keeps it honest.

Only usage numbers are stored: no prompts, answers, keys or user data.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("legalai.llm_daily_quota")

Key = tuple[str, str]  # (rate-limit account, model)
DAILY_LIMIT_MESSAGE = re.compile(r"(tokens|requests) per day|\b(TPD|RPD)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DailyLimits:
    tokens_per_day: int
    requests_per_day: int | None = None


class DailyCapacityReached(Exception):
    """No model allowed for this request has daily capacity left; answered 503 DAILY_CAPACITY_REACHED."""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("today's answer capacity is used up")
        self.retry_after_seconds = max(1, int(round(retry_after_seconds)))


def is_daily_limit_error(exc: Exception) -> bool:
    """A provider 429 that names a per-day limit (Groq: "tokens per day (TPD)")."""
    text = " ".join(str(part) for part in (getattr(exc, "provider_message", None), getattr(exc, "provider_code", None), exc) if part)
    return getattr(exc, "http_status", None) == 429 and bool(DAILY_LIMIT_MESSAGE.search(text))


def utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def seconds_until_utc_reset(now: float) -> float:
    current = datetime.fromtimestamp(now, timezone.utc)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - current).total_seconds()


class DailyQuota:
    """Per-model daily usage with limits; thread-safe; persisted to ``path`` (None keeps it in memory)."""

    def __init__(self, path: Path | None, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else None
        self._clock = clock
        self._lock = threading.Lock()
        self._limits: dict[Key, DailyLimits] = {}
        self._state = self._load()

    # -- persistence ----------------------------------------------------------------------------------------------

    def _empty(self) -> dict[str, Any]:
        return {"day": utc_day(self._clock()), "models": {}}

    def _load(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return self._empty()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("models"), dict):
                raise ValueError("unexpected layout")
            return state
        except (OSError, ValueError) as exc:
            logger.warning("daily usage file unreadable, starting a new count: %s", type(exc).__name__)
            return self._empty()

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".llm_daily_usage.", dir=self.path.parent)
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(self._state, file, indent=1, sort_keys=True)
        os.replace(temporary, self.path)

    def _roll(self) -> None:
        """A new UTC day starts a new count; an exhaustion mark that reaches beyond the reset is kept."""
        today = utc_day(self._clock())
        if self._state.get("day") == today:
            return
        now = self._clock()
        carried = {name: {"tokens": 0, "requests": 0, "exhausted_until": entry.get("exhausted_until")}
                   for name, entry in self._state.get("models", {}).items()
                   if (entry.get("exhausted_until") or 0) > now}
        self._state = {"day": today, "models": carried}

    def _entry(self, key: Key) -> dict[str, Any]:
        return self._state["models"].setdefault(f"{key[0]}/{key[1]}", {"tokens": 0, "requests": 0, "exhausted_until": None})

    # -- configuration -----------------------------------------------------------------------------------------------

    def configure(self, key: Key, limits: DailyLimits) -> None:
        with self._lock:
            self._limits[key] = limits

    def is_tracked(self, key: Key) -> bool:
        with self._lock:
            return key in self._limits

    # -- checks and accounting --------------------------------------------------------------------------------------

    def can_serve(self, key: Key, estimated_tokens: int) -> bool:
        """True when ``key`` is untracked, or has the tokens and a request left today and is not marked exhausted."""
        with self._lock:
            limits = self._limits.get(key)
            if limits is None:
                return True
            self._roll()
            entry = self._entry(key)
            if (entry.get("exhausted_until") or 0) > self._clock():
                return False
            if limits.requests_per_day is not None and entry["requests"] >= limits.requests_per_day:
                return False
            return entry["tokens"] + max(0, estimated_tokens) <= limits.tokens_per_day

    def seconds_until_available(self, key: Key) -> float:
        """When capacity returns for ``key``: the exhaustion mark, else the UTC reset."""
        with self._lock:
            self._roll()
            now = self._clock()
            until = self._entry(key).get("exhausted_until") or 0
            return max(until - now, 0.0) if until > now else seconds_until_utc_reset(now)

    def record(self, key: Key, tokens: int | None, *, requests: int = 1) -> None:
        """Add one answered request's provider-reported tokens (prompt + completion)."""
        with self._lock:
            if key not in self._limits:
                return
            self._roll()
            entry = self._entry(key)
            entry["tokens"] += max(0, int(tokens or 0))
            entry["requests"] += requests
            self._save()

    def mark_exhausted(self, key: Key, retry_after_seconds: float | None) -> None:
        """The provider reported the daily limit: no requests to ``key`` until its retry time (else the UTC reset)."""
        with self._lock:
            self._roll()
            now = self._clock()
            seconds = retry_after_seconds if retry_after_seconds else seconds_until_utc_reset(now)
            entry = self._entry(key)
            entry["exhausted_until"] = max(entry.get("exhausted_until") or 0, now + seconds)
            self._save()
            logger.warning("daily_limit model=%s/%s exhausted_for_s=%.0f", key[0], key[1], seconds)

    # -- /health --------------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._roll()
            now = self._clock()
            models = {}
            for key, limits in sorted(self._limits.items()):
                entry = self._entry(key)
                until = entry.get("exhausted_until") or 0
                models[f"{key[0]}/{key[1]}"] = {
                    "tokens_used": entry["tokens"],
                    "tokens_per_day": limits.tokens_per_day,
                    "tokens_remaining": max(0, limits.tokens_per_day - entry["tokens"]),
                    "requests_used": entry["requests"],
                    "requests_per_day": limits.requests_per_day,
                    "exhausted_for_seconds": round(until - now) if until > now else 0,
                }
            return {"day_utc": self._state["day"], "resets_in_seconds": round(seconds_until_utc_reset(now)), "models": models}


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
