"""ASGI guards applied before any route runs (SEC-006, SEC-008).

``OriginCheckMiddleware`` (CSRF defence in depth, on top of SameSite=Lax):
a state-changing request (POST, PUT, PATCH, DELETE) that carries the auth
cookie must come from an allowed origin. The Origin header is checked, or the
Referer's origin when Origin is absent. A request with neither header is let
through: browsers always send Origin on cross-origin writes, so a missing
header means a non-browser client, which cannot ride a victim's cookies.
Requests without the auth cookie (anonymous, or bearer-token clients) are
not CSRF targets and are not checked.

``BodySizeLimitMiddleware``: a request whose Content-Length exceeds the
upload limit plus multipart overhead gets 413 before its body is read.
Chunked uploads (no Content-Length) are still bounded by the streaming checks
in the upload routes.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from backend.app.core.security import COOKIE_NAME

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MULTIPART_OVERHEAD_BYTES = 1024 * 1024

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _headers(scope: Scope) -> dict[str, str]:
    return {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}


def _has_auth_cookie(cookie_header: str) -> bool:
    return any(part.strip().split("=", 1)[0] == COOKIE_NAME for part in cookie_header.split(";") if part.strip())


def request_origin(headers: dict[str, str]) -> str | None:
    origin = headers.get("origin")
    if origin:
        return origin.strip().rstrip("/")
    referer = headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
        return "null"
    return None


async def _json_response(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"detail": {"code": code, "message": message}}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {origin.rstrip("/") for origin in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method", "").upper() in UNSAFE_METHODS:
            headers = _headers(scope)
            if _has_auth_cookie(headers.get("cookie", "")):
                origin = request_origin(headers)
                if origin is not None and origin not in self.allowed:
                    await _json_response(
                        send, 403, "CSRF_ORIGIN_REJECTED", "This request came from a site that is not allowed to act on your account."
                    )
                    return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = _headers(scope).get("content-length")
            if length and length.isdigit() and int(length) > self.max_body_bytes:
                await _json_response(send, 413, "REQUEST_TOO_LARGE", "The upload is larger than the allowed size.")
                return
        await self.app(scope, receive, send)


def max_request_body_bytes(max_upload_size_mb: int) -> int:
    return max_upload_size_mb * 1024 * 1024 + MULTIPART_OVERHEAD_BYTES
