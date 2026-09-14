"""Query history persistence for authenticated professional queries.

Public/anonymous conversations stay session-local and are not written to the
shared PostgreSQL history table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import QueryHistory

PROFESSIONAL_MODE = "professional"
PUBLIC_MODE = "public"
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100


def _normalize_mode(mode: str | None) -> str:
    return (mode or "").strip().lower()


def _coerce_response_json(response_json: Any) -> dict[str, Any] | None:
    if response_json is None:
        return None
    if isinstance(response_json, dict):
        return response_json
    if hasattr(response_json, "model_dump"):
        dumped = response_json.model_dump()
        if isinstance(dumped, dict):
            return dumped
    raise ValueError("response_json must be a JSON object.")


def save_query_history(
    db: Session,
    *,
    query_text: str,
    mode: str,
    user_id: int | None = None,
    session_id: str | None = None,
    response_json: Any = None,
    generation_backend: str | None = None,
) -> QueryHistory | None:
    """Persist a professional query for an authenticated user.

    Returns None without writing a row when:
    - mode is public/anonymous
    - user_id is missing (cannot enforce isolation)
    """
    cleaned_text = (query_text or "").strip()
    if not cleaned_text:
        raise ValueError("query_text must not be empty.")

    normalized_mode = _normalize_mode(mode)
    if not normalized_mode:
        raise ValueError("mode must not be empty.")

    if normalized_mode != PROFESSIONAL_MODE or user_id is None:
        return None

    record = QueryHistory(
        user_id=user_id,
        session_id=(session_id.strip() if session_id and session_id.strip() else None),
        mode=PROFESSIONAL_MODE,
        query_text=cleaned_text,
        response_json=_coerce_response_json(response_json),
        generation_backend=(
            generation_backend.strip() if generation_backend and generation_backend.strip() else None
        ),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_query_history(
    db: Session,
    *,
    user_id: int,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> list[QueryHistory]:
    """Return the latest professional queries for a single authenticated user."""
    if user_id is None:
        raise ValueError("user_id is required.")
    if limit < 1 or limit > MAX_HISTORY_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_HISTORY_LIMIT}.")

    return (
        db.query(QueryHistory)
        .filter(QueryHistory.user_id == user_id)
        .filter(QueryHistory.mode == PROFESSIONAL_MODE)
        .order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc())
        .limit(limit)
        .all()
    )
