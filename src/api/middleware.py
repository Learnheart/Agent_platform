"""API Middleware — authentication and tenant context.

See docs/architecture/10-api-contracts.md.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from src.core.models import AuthContext
from src.core.security import validate_jwt_token

logger = logging.getLogger(__name__)


async def get_auth_context(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> AuthContext:
    """Extract and validate authentication credentials.

    Supports:
    - Bearer JWT token (builders)
    - X-API-Key (end users / programmatic)
    """
    # Try Bearer token first
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            from src.core.config import get_settings
            secret = get_settings().auth.jwt_secret or "dev-secret"
            auth_ctx = validate_jwt_token(token, secret=secret)
            return auth_ctx
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    # Try API key
    if x_api_key:
        # Phase 1: simple validation — in production, lookup in DB
        # For now, extract tenant from key prefix convention: "apt_{tenant}_{key}"
        parts = x_api_key.split("_", 2)
        if len(parts) >= 2:
            return AuthContext(
                user_id="api_key_user",
                tenant_id=parts[1] if len(parts) > 1 else "",
                user_type="end_user",
            )
        raise HTTPException(status_code=401, detail="Invalid API key format")

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_builder(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Require builder-level access."""
    if auth.user_type != "builder":
        raise HTTPException(status_code=403, detail="Builder access required")
    return auth
