"""One error body for every error response (step 16, BE-003).

Every non-2xx response from the API has the body

    {"error": "<safe, human-readable message>", "code": "<STABLE_CODE>", "detail": {...} | null}

- ``error`` is written for the person using the app. It never contains a stack trace, a path, or the text of an
  unexpected exception.
- ``code`` is the stable machine code. Clients branch on it, never on ``error``.
- ``detail`` is optional structured data (per-field validation errors, ``document_id``, ``request_id`` for a 500).

Routes raise ``HTTPException(status_code, detail={"code": ..., "message": ..., **extra})``; ``extra`` becomes
``detail``. An ``HTTPException`` with a plain string detail (Starlette's own 404/405, a library) gets a code from its
status. Request validation becomes ``VALIDATION_ERROR`` with the failing fields, without the submitted values.
Anything else is a 500 ``INTERNAL_ERROR`` with a generic message and the request ID; the exception is only logged.

Every response carries ``X-Request-ID``. An incoming ``X-Request-ID`` is reused when it is short and plain;
otherwise one is generated. ``legalai.*`` log lines written while a request is handled end in ``[request_id=...]``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("legalai.errors")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("legalai_request_id", default=None)

INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Please try again in a moment."
VALIDATION_ERROR_MESSAGE = "Some of the submitted information is missing or invalid."

# Code and message for an HTTPException that carries no code of its own (Starlette 404/405, libraries).
STATUS_FALLBACKS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "The request could not be processed."),
    401: ("NOT_AUTHENTICATED", "Please sign in to continue."),
    403: ("FORBIDDEN", "You do not have access to this feature."),
    404: ("NOT_FOUND", "The requested resource was not found."),
    405: ("METHOD_NOT_ALLOWED", "This action is not supported here."),
    409: ("CONFLICT", "The request conflicts with the current state."),
    413: ("REQUEST_TOO_LARGE", "The upload is larger than the allowed size."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "This file type is not supported."),
    422: ("VALIDATION_ERROR", VALIDATION_ERROR_MESSAGE),
    429: ("RATE_LIMITED", "Too many requests. Please wait and try again."),
    503: ("SERVICE_UNAVAILABLE", "The service is temporarily unavailable. Please try again later."),
}
# Starlette's own string details, which are safe to show as they are.
_SAFE_STRING_DETAILS = {"Not Found", "Method Not Allowed"}


def error_body(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": message, "code": code, "detail": detail or None}


def api_error(status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None, **detail: Any) -> HTTPException:
    """An HTTPException in the route convention: the handler turns it into {error: message, code, detail}."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **detail}, headers=headers)


def current_request_id() -> str | None:
    return _request_id.get()


def _fallback(status_code: int) -> tuple[str, str]:
    if status_code in STATUS_FALLBACKS:
        return STATUS_FALLBACKS[status_code]
    if status_code >= 500:
        return "INTERNAL_ERROR", INTERNAL_ERROR_MESSAGE
    return f"HTTP_{status_code}", "The request could not be completed."


def http_exception_body(status_code: int, detail: Any) -> dict[str, Any]:
    """The unified body for an HTTPException's detail: a {code, message, ...} dict, or a plain string."""
    if isinstance(detail, dict) and isinstance(detail.get("code"), str) and isinstance(detail.get("message"), str):
        extra = {key: value for key, value in detail.items() if key not in ("code", "message")}
        return error_body(detail["code"], detail["message"], extra)
    code, message = _fallback(status_code)
    if isinstance(detail, str) and detail in _SAFE_STRING_DETAILS:
        message = {"Not Found": STATUS_FALLBACKS[404][1], "Method Not Allowed": STATUS_FALLBACKS[405][1]}[detail]
    return error_body(code, message)


def validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Per-field errors without the submitted values (FastAPI's default echoes them, passwords included)."""
    fields = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        fields.append({
            "field": ".".join(location),
            "message": str(error.get("msg", "Invalid value.")),
            "type": str(error.get("type", "value_error")),
        })
    return fields


def internal_error_body(request_id: str | None) -> dict[str, Any]:
    return error_body("INTERNAL_ERROR", INTERNAL_ERROR_MESSAGE, {"request_id": request_id} if request_id else None)


def _request_id_from_scope(scope: Scope) -> str | None:
    state = scope.get("state")
    return state.get("request_id") if isinstance(state, dict) else None


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(http_exception_body(exc.status_code, exc.detail), status_code=exc.status_code, headers=exc.headers)


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = error_body("VALIDATION_ERROR", VALIDATION_ERROR_MESSAGE, {"fields": validation_errors(exc)})
    return JSONResponse(body, status_code=422)


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Backstop for an exception raised outside UnhandledErrorMiddleware (in an outer middleware)."""
    request_id = _request_id_from_scope(request.scope)
    logger.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path, exc_info=exc)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(internal_error_body(request_id), status_code=500, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)


async def send_error(send: Send, status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
    """Send a unified error body from a pure ASGI middleware."""
    body = json.dumps(error_body(code, message)).encode("utf-8")
    raw_headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw_headers += [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status_code, "headers": raw_headers})
    await send({"type": "http.response.body", "body": body})


class UnhandledErrorMiddleware:
    """Turn an unexpected exception into the 500 body. It sits inside CORS, so the browser can read the answer."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:  # the status line is gone; nothing better can be sent
                raise
            logger.error("unhandled %s on %s %s", type(exc).__name__, scope.get("method"), scope.get("path"), exc_info=exc)
            body = json.dumps(internal_error_body(_request_id_from_scope(scope))).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    """Outermost: assign the request ID, expose it to handlers and logs, and return it on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers", [])).get(REQUEST_ID_HEADER.lower().encode("latin-1"), b"").decode("latin-1").strip()
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode("latin-1"))]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(token)


def install_request_id_logging() -> None:
    """Append the current request ID to every legalai.* log record (whatever handler formats it)."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_legalai_request_id", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        request_id = _request_id.get()
        record.request_id = request_id
        if request_id and record.name.startswith("legalai") and isinstance(record.msg, str):
            # The ID matches _REQUEST_ID_PATTERN, so it holds no "%" and leaves %-formatting intact.
            record.msg = f"{record.msg} [request_id={request_id}]"
        return record

    factory._legalai_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
