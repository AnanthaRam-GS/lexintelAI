"""Per-model pacing of LLM requests (step 23): token buckets and one FIFO wait queue.

Groq's free tier allows 8,000 tokens per minute per model (each model has its own limits, step 22), and it rejects a
request with HTTP 429 when the tokens it asks for (prompt + max output) exceed what is left in the minute. Sending
requests as they arrive therefore fails under a burst. Instead every request first waits here for capacity:

- One ``TokenBucket`` per (account, model), sized from the model's tokens- and requests-per-minute limits. Buckets
  refill continuously. Groq's ``x-ratelimit-remaining-tokens`` / ``x-ratelimit-reset-tokens`` headers, when present,
  replace the estimate with the provider's own count; a 429 blocks the bucket until ``retry-after`` (or the reset).
  ``x-ratelimit-remaining-requests`` is Groq's *daily* request count: at 0 the bucket blocks until its reset.
- One FIFO queue. A waiting request names its candidate models in order (primary, then fallback); the request at
  the head takes the first candidate with capacity, and later requests wait behind it. Each request waits at most
  ``LEGALAI_LLM_QUEUE_MAX_WAIT_SECONDS``; then ``PacingTimeout`` (answered ``MODEL_BUSY`` with ``Retry-After``).

Waiting holds nothing else: no generation slot (``rate_limit.generation_slots`` is taken after the grant) and never
the model inference lock (``inference_lock``, used only by local embedding/reranking, which finish before generation).

Only models with known limits are paced; any other key passes straight through.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("legalai.llm_pacing")

Key = tuple[str, str]  # (rate-limit account, model)

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration_seconds(value: Any) -> float | None:
    """Groq reset durations ("44.655s", "1m26.4s", "705ms", "2h3m") or plain seconds ("7") -> seconds."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    total, matched = 0.0, ""
    for number, unit in _DURATION_PART.findall(text):
        total += float(number) * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
        matched += number + unit
    return total if matched and matched == text.replace(" ", "") else None


def _header(headers: Mapping[str, Any] | None, name: str) -> Any:
    if not headers:
        return None
    for key, value in headers.items():
        if str(key).lower() == name:
            return value
    return None


def retry_after_seconds(headers: Mapping[str, Any] | None) -> float | None:
    """How long the provider says to wait: ``retry-after``, else the token-window reset."""
    for name in ("retry-after", "x-ratelimit-reset-tokens"):
        seconds = parse_duration_seconds(_header(headers, name))
        if seconds is not None:
            return seconds
    return None


@dataclass(frozen=True)
class ModelLimits:
    tokens_per_minute: int
    requests_per_minute: int


@dataclass
class TokenBucket:
    """Tokens and requests available to one model; both refill linearly over a minute."""

    limits: ModelLimits
    tokens: float = field(init=False)
    requests: float = field(init=False)
    blocked_until: float = 0.0
    updated_at: float | None = None

    def __post_init__(self) -> None:
        self.tokens = float(self.limits.tokens_per_minute)
        self.requests = float(self.limits.requests_per_minute)

    @property
    def token_rate(self) -> float:
        return self.limits.tokens_per_minute / 60.0

    @property
    def request_rate(self) -> float:
        return self.limits.requests_per_minute / 60.0

    def cost_for(self, tokens: int) -> float:
        # A request larger than a whole minute's tokens can never fit; it waits for a full bucket instead
        # (the request-size guard keeps real requests under the per-request ceiling).
        return float(min(tokens, self.limits.tokens_per_minute))

    def refresh(self, now: float) -> None:
        if self.updated_at is not None and now > self.updated_at:
            elapsed = now - self.updated_at
            self.tokens = min(float(self.limits.tokens_per_minute), self.tokens + elapsed * self.token_rate)
            self.requests = min(float(self.limits.requests_per_minute), self.requests + elapsed * self.request_rate)
        self.updated_at = now

    def wait_seconds(self, tokens: int, now: float) -> float:
        """Seconds until ``tokens`` and one request are available (0 when they are now)."""
        self.refresh(now)
        cost = self.cost_for(tokens)
        waits = [max(0.0, self.blocked_until - now)]
        if self.tokens < cost:
            waits.append((cost - self.tokens) / self.token_rate)
        if self.requests < 1.0:
            waits.append((1.0 - self.requests) / self.request_rate)
        return max(waits)

    def take(self, tokens: int, now: float) -> None:
        self.refresh(now)
        self.tokens -= self.cost_for(tokens)
        self.requests -= 1.0

    def observe(self, headers: Mapping[str, Any] | None, now: float) -> bool:
        """Adopt the provider's own remaining counts. Returns True when a rate-limit header was present."""
        self.refresh(now)
        seen = False
        remaining_tokens = _header(headers, "x-ratelimit-remaining-tokens")
        if remaining_tokens is not None:
            try:
                self.tokens = min(float(self.limits.tokens_per_minute), max(0.0, float(remaining_tokens)))
                seen = True
            except ValueError:
                pass
        remaining_requests = _header(headers, "x-ratelimit-remaining-requests")
        if remaining_requests is not None:
            seen = True
            try:
                if float(remaining_requests) <= 0:
                    # Groq's request counters are per day: nothing more until their reset.
                    reset = parse_duration_seconds(_header(headers, "x-ratelimit-reset-requests")) or 60.0
                    self.blocked_until = max(self.blocked_until, now + reset)
            except ValueError:
                pass
        return seen

    def block(self, seconds: float, now: float) -> None:
        """A 429: nothing is available until the provider's retry time."""
        self.refresh(now)
        self.tokens = 0.0
        self.blocked_until = max(self.blocked_until, now + max(0.0, seconds))


class PacingTimeout(Exception):
    """No candidate model had capacity within the request's queue deadline."""

    def __init__(self, retry_after_seconds: float, waited_seconds: float) -> None:
        super().__init__(f"no model capacity within the queue wait ({waited_seconds:.1f}s waited)")
        self.retry_after_seconds = max(1, math.ceil(retry_after_seconds))
        self.waited_seconds = waited_seconds


@dataclass
class _Ticket:
    number: int
    candidates: list[tuple[Key, int]]
    granted: Key | None = None


class LLMPacer:
    """Token buckets per (account, model) and one FIFO queue in front of them."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._condition = threading.Condition()
        self._buckets: dict[Key, TokenBucket] = {}
        self._queue: deque[_Ticket] = deque()
        self._numbers = itertools.count(1)

    # -- configuration ---------------------------------------------------------------------------------------------

    def configure(self, key: Key, limits: ModelLimits) -> None:
        """Register (or resize) a model's bucket. Unregistered keys are not paced."""
        with self._condition:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.limits != limits:
                fresh = TokenBucket(limits)
                fresh.updated_at = self._clock()
                if bucket is not None:
                    fresh.tokens = min(fresh.tokens, bucket.tokens)
                    fresh.blocked_until = bucket.blocked_until
                self._buckets[key] = fresh
                self._condition.notify_all()

    def register(self, key: Key, limits: ModelLimits) -> None:
        """Register a bucket only if ``key`` has none yet (per request; never resizes or refills an existing one)."""
        with self._condition:
            if key not in self._buckets:
                bucket = TokenBucket(limits)
                bucket.updated_at = self._clock()
                self._buckets[key] = bucket

    def is_paced(self, key: Key) -> bool:
        with self._condition:
            return key in self._buckets

    def reset(self) -> None:
        with self._condition:
            self._buckets.clear()
            self._queue.clear()
            self._condition.notify_all()

    # -- the queue -------------------------------------------------------------------------------------------------

    def acquire(self, candidates: list[tuple[Key, int]], *, timeout_seconds: float) -> tuple[Key, float]:
        """Wait in FIFO order until a candidate (key, estimated tokens) has capacity; take it.

        Returns (granted key, seconds waited). An unpaced candidate (no bucket) is always available, in its place in
        the order; a request with only unpaced candidates does not queue. Raises ``PacingTimeout`` when nothing
        frees up within ``timeout_seconds``.
        """
        started = self._clock()
        deadline = started + max(0.0, timeout_seconds)
        with self._condition:
            if all(key not in self._buckets for key, _tokens in candidates):
                return candidates[0][0], 0.0
            ticket = _Ticket(next(self._numbers), list(candidates))
            self._queue.append(ticket)
            try:
                while True:
                    now = self._clock()
                    if self._queue[0] is ticket:
                        key = self._first_available(ticket, now)
                        if key is not None:
                            if key in self._buckets:
                                self._buckets[key].take(dict(ticket.candidates)[key], now)
                            ticket.granted = key
                            return key, now - started
                    if now >= deadline:
                        raise PacingTimeout(self._ticket_wait(ticket, now), now - started)
                    pause = deadline - now
                    if self._queue[0] is ticket:
                        pause = min(pause, max(0.01, self._ticket_wait(ticket, now)))
                    self._condition.wait(timeout=pause)
            finally:
                self._queue.remove(ticket)
                self._condition.notify_all()

    def has_capacity(self, key: Key, tokens: int) -> bool:
        """True when ``key`` could serve ``tokens`` now and nobody is queued ahead (unpaced keys always can)."""
        with self._condition:
            bucket = self._buckets.get(key)
            if bucket is None:
                return True
            return not self._queue and bucket.wait_seconds(tokens, self._clock()) == 0.0

    def take_now(self, key: Key, tokens: int) -> bool:
        """Take capacity on ``key`` without queueing, if it is free now (immediate fallback after a 429)."""
        with self._condition:
            bucket = self._buckets.get(key)
            if bucket is None:
                return True
            now = self._clock()
            if self._queue or bucket.wait_seconds(tokens, now) > 0.0:
                return False
            bucket.take(tokens, now)
            return True

    def _first_available(self, ticket: _Ticket, now: float) -> Key | None:
        for key, tokens in ticket.candidates:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.wait_seconds(tokens, now) == 0.0:
                return key
        return None

    def _ticket_wait(self, ticket: _Ticket, now: float) -> float:
        waits = [self._buckets[key].wait_seconds(tokens, now) for key, tokens in ticket.candidates if key in self._buckets]
        return min(waits) if waits else 0.0

    # -- provider feedback ------------------------------------------------------------------------------------------

    def observe(self, key: Key, headers: Mapping[str, Any] | None) -> None:
        """Adopt the provider's rate-limit headers for ``key`` (success or error response)."""
        with self._condition:
            bucket = self._buckets.get(key)
            if bucket is not None and bucket.observe(headers, self._clock()):
                self._condition.notify_all()

    def block(self, key: Key, seconds: float) -> None:
        with self._condition:
            bucket = self._buckets.get(key)
            if bucket is not None:
                bucket.block(seconds, self._clock())
                self._condition.notify_all()

    def wait_seconds(self, key: Key, tokens: int) -> float:
        with self._condition:
            bucket = self._buckets.get(key)
            return 0.0 if bucket is None else bucket.wait_seconds(tokens, self._clock())

    # -- /health ---------------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Queue depth, the estimated wait of the last queued request, and each model's available tokens."""
        with self._condition:
            now = self._clock()
            models = {}
            for (account, model), bucket in sorted(self._buckets.items()):
                bucket.refresh(now)
                models[f"{account}/{model}"] = {
                    "tokens_available": int(bucket.tokens),
                    "tokens_per_minute": bucket.limits.tokens_per_minute,
                    "requests_per_minute": bucket.limits.requests_per_minute,
                    "blocked_seconds": round(max(0.0, bucket.blocked_until - now), 1),
                }
            return {"queue_depth": len(self._queue), "estimated_wait_seconds": round(self._simulated_wait(now), 1),
                    "models": models}

    def _simulated_wait(self, now: float) -> float:
        """Serve the queued tickets in order on copies of the buckets; the time until the last one is served."""
        buckets = {key: _copy(bucket) for key, bucket in self._buckets.items()}
        t = now
        for ticket in self._queue:
            paced = [(key, tokens) for key, tokens in ticket.candidates if key in buckets]
            if not paced:
                continue
            key, tokens = min(paced, key=lambda item: buckets[item[0]].wait_seconds(item[1], t))
            t += buckets[key].wait_seconds(tokens, t)
            buckets[key].take(tokens, t)
        return t - now


def _copy(bucket: TokenBucket) -> TokenBucket:
    clone = TokenBucket(bucket.limits)
    clone.tokens, clone.requests = bucket.tokens, bucket.requests
    clone.blocked_until, clone.updated_at = bucket.blocked_until, bucket.updated_at
    return clone


llm_pacer = LLMPacer()
