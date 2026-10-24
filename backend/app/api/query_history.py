"""Query history API endpoints for LegalAI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.core.errors import api_error
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.history import QueryHistoryItem
from backend.app.services.query_history import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    list_query_history,
)

router = APIRouter(tags=["Query History"])


@router.get("/query/history", response_model=list[QueryHistoryItem], operation_id="get_query_history")
@router.get("/query-history", response_model=list[QueryHistoryItem], operation_id="get_query_history_legacy")
def get_query_history(
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[QueryHistoryItem]:
    """Return the latest professional queries for the authenticated user only."""
    try:
        rows = list_query_history(db, user_id=current_user.id, limit=limit)
    except ValueError as exc:
        # list_query_history raises only its own fixed messages ("limit must be between 1 and 50.").
        raise api_error(status.HTTP_400_BAD_REQUEST, "INVALID_HISTORY_REQUEST", str(exc)) from exc
    return [QueryHistoryItem.model_validate(row) for row in rows]
