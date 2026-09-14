"""Query history API contracts for LegalAI."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QueryHistoryItem(BaseModel):
    """Persisted professional query history row for the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    query_text: str
    response_json: dict | None = None
    generation_backend: str | None = None
    created_at: datetime
