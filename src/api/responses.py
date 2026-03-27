"""API response envelope utilities.

Standard response format for all API endpoints.
See docs/architecture/10-api-contracts.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    """Metadata included in every response."""

    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str | None = None


class SuccessResponse(BaseModel):
    """Standard success response envelope."""

    data: Any
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class ErrorDetail(BaseModel):
    """Error detail in response."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


def success(data: Any, **meta_kwargs: Any) -> dict[str, Any]:
    """Build a success response dict."""
    return SuccessResponse(
        data=data,
        meta=ResponseMeta(**meta_kwargs),
    ).model_dump(mode="json")


def error(code: str, message: str, status_code: int = 500, details: dict | None = None) -> dict[str, Any]:
    """Build an error response dict."""
    return ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or {}),
    ).model_dump(mode="json")
