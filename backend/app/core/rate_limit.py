"""In-memory request limits (SEC-001, SEC-003).

- ``query_limiter``: sliding-window rate limits per client IP (public query routes)
  and per user (professional query routes), per minute and per day.
- ``login_throttle``: failed-login counting per account key and per client IP,
  with a lockout once a limit is reached within the window.
- ``generation_slots``: a process-wide cap on concurrent LLM generations.

The state lives in this process only. Several worker processes, or several
hosts, each keep their own counters, so the effective limit multiplies; a
shared store (for example Redis) is needed before scaling out. See docs/SECURITY.md.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import ipaddress
import math
import threading
import time
from typing import Callable, Iterator

from fastapi import HTTPException, Request, status

from backend.app.core.config import Settings

MINUTE = 60
DAY = 24 * 60 * 60


class SlidingWindowLimiter:
    """Counts events per key; ``hit`` records one unless a limit is already full."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limits: list[tuple[int, int]]) -> int | None:
        """Record an event, or return the seconds to wait if any (limit, window) is reached."""
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            longest = max(window for _limit, window in limits)
            while events and events[0] <= now - longest:
                events.popleft()
            waits = []
            for limit, window in limits:
                in_window = [stamp for stamp in events if stamp > now - window]
                if limit >= 0 and len(in_window) >= limit:
                    waits.append(in_window[0] + window - now)
            if waits:
                return max(1, math.ceil(max(waits)))
            events.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class LoginThrottle:
    """Failed-login counting and lockout, keyed by normalized email and by client IP.

    Unknown emails are counted exactly like real accounts, so the response never
    reveals whether an account exists.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, keys: list[str]) -> int | None:
        now = self._clock()
        with self._lock:
            waits = [until - now for key in keys if (until := self._locked_until.get(key, 0.0)) > now]
        return max(1, math.ceil(max(waits))) if waits else None

    def record_failure(self, limits: dict[str, int], *, window_seconds: int, lockout_seconds: int) -> None:
        now = self._clock()
        with self._lock:
            for key, limit in limits.items():
                failures = self._failures.setdefault(key, deque())
                while failures and failures[0] <= now - window_seconds:
                    failures.popleft()
                failures.append(now)
                if len(failures) >= limit:
                    self._locked_until[key] = now + lockout_seconds
                    failures.clear()

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


class GenerationSlots:
    """At most N concurrent LLM generations per process; the limit follows settings."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphore: threading.BoundedSemaphore | None = None
        self._size = 0

    def _for(self, size: int) -> threading.BoundedSemaphore:
        with self._lock:
            if self._semaphore is None or self._size != size:
                self._semaphore = threading.BoundedSemaphore(max(1, size))
                self._size = size
            return self._semaphore

    @contextmanager
    def slot(self, size: int, wait_seconds: float) -> Iterator[bool]:
        """Yields True with a slot held, or False if none freed up within ``wait_seconds``."""
        semaphore = self._for(size)
        acquired = semaphore.acquire(timeout=max(0.0, wait_seconds))
        try:
            yield acquired
        finally:
            if acquired:
                semaphore.release()

    def reset(self) -> None:
        with self._lock:
            self._semaphore = None
            self._size = 0


query_limiter = SlidingWindowLimiter()
login_throttle = LoginThrottle()
generation_slots = GenerationSlots()


def reset_limits() -> None:
    """Clear all in-memory counters (tests)."""
    query_limiter.reset()
    login_throttle.reset()
    generation_slots.reset()


def _trusted_networks(settings: Settings) -> list[ipaddress._BaseNetwork]:
    networks = []
    for item in (settings.trusted_proxies or "").split(","):
        item = item.strip()
        if item:
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                continue
    return networks


def _is_trusted(address: str, networks: list[ipaddress._BaseNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


def client_ip(request: Request, settings: Settings) -> str:
    """The client address; X-Forwarded-For is used only when the peer is a configured trusted proxy.

    With trusted proxies, the right-most address in X-Forwarded-For that is not
    itself a trusted proxy is the client (earlier entries are client-supplied).
    """
    peer = request.client.host if request.client else "unknown"
    networks = _trusted_networks(settings)
    if not networks or not _is_trusted(peer, networks):
        return peer
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    for address in reversed(forwarded):
        if not _is_trusted(address, networks):
            return address
    return forwarded[0] if forwarded else peer


def too_many_requests(code: str, message: str, retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": code, "message": message, "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def wait_phrase(seconds: int) -> str:
    if seconds < 90:
        return "about a minute"
    if seconds < 3600:
        return f"about {math.ceil(seconds / 60)} minutes"
    return f"about {math.ceil(seconds / 3600)} hours"
