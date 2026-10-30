"""Safe logging of answer-provider HTTP errors (step 11d).

Non-2xx provider responses are logged with the HTTP status and the provider's
own error type, code and message, so failures such as Groq HTTP 400 can be
diagnosed. Only ``error.type``, ``error.code``/``status`` and ``error.message``
are read (never fields such as Groq's ``failed_generation``, which can echo
model output). The message is whitespace-collapsed, has anything shaped like
an API key or bearer token redacted, and is truncated. Prompt text, keys and
document text are never logged.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("legalai.provider_errors")

MAX_MESSAGE_CHARS = 240
# Groq, Google, bearer tokens, OpenAI-style (DeepSeek, OpenRouter "sk-or-...") and NVIDIA API catalog ("nvapi-") keys.
_SECRET_LIKE = re.compile(r"(gsk_[A-Za-z0-9]{6,}|AIza[0-9A-Za-z_\-]{10,}|Bearer\s+\S+|sk-[A-Za-z0-9\-]{10,}|nvapi-[A-Za-z0-9_\-]{10,})")


def sanitize_provider_message(message: Any) -> str | None:
    if message is None:
        return None
    text = " ".join(str(message).split())
    text = _SECRET_LIKE.sub("[redacted]", text)
    return text[:MAX_MESSAGE_CHARS] + ("..." if len(text) > MAX_MESSAGE_CHARS else "")


def log_provider_http_error(provider: str, http_status: int | None, payload: Any) -> None:
    """Log one sanitized provider error line; ``payload`` is the parsed error body (or its raw text)."""
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {"message": error}
    message = error.get("message") if error else (payload if isinstance(payload, str) else None)
    logger.warning(
        "provider_http_error provider=%s status=%s type=%s code=%s message=%s",
        provider,
        http_status,
        error.get("type") or error.get("status"),
        error.get("code"),
        sanitize_provider_message(message),
    )
