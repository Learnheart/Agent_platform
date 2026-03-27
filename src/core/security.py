"""Security utilities: JWT validation, API key hashing.

See docs/architecture/10-api-contracts.md Section 2.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from src.core.errors import AuthError
from src.core.models import AuthContext


def create_jwt_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    *,
    secret: str,
    algorithm: str = "HS256",
    issuer: str = "agent-platform",
    audience: str = "agent-platform",
    expiry_seconds: int = 3600,
) -> str:
    """Create a JWT token for builder authentication."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(seconds=expiry_seconds),
        "iss": issuer,
        "aud": audience,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def validate_jwt_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    issuer: str = "agent-platform",
    audience: str = "agent-platform",
) -> AuthContext:
    """Validate a JWT token and return AuthContext.

    Raises AuthError on invalid/expired tokens.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            issuer=issuer,
            audience=audience,
        )
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower():
            raise AuthError("Token expired", status_code=401) from e
        raise AuthError("Invalid token", status_code=401) from e

    return AuthContext(
        user_id=payload["sub"],
        tenant_id=payload["tenant_id"],
        user_type="builder",
        roles=payload.get("roles", []),
    )


def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256 for storage/lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key in format sk_live_{random_32_chars}."""
    random_part = secrets.token_urlsafe(24)  # ~32 chars
    return f"sk_live_{random_part}"
