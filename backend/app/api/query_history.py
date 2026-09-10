"""Query history API endpoints for LegalAI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.history import QueryHistoryItem
from backend.app.services.query_history import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    list_query_history,
)

router = APIRouter(prefix="/query-history", tags=["Query History"])


@router.get("", response_model=list[QueryHistoryItem])
def get_query_history(
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
) -> list[QueryHistoryItem]:
    """Return the latest professional queries for the authenticated user only."""
    try:
        rows = list_query_history(db, user_id=current_user.id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [QueryHistoryItem.model_validate(row) for row in rows]
