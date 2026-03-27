"""Tests for security utilities."""

import pytest

from src.core.errors import AuthError
from src.core.security import (
    create_jwt_token,
    generate_api_key,
    hash_api_key,
    validate_jwt_token,
)

SECRET = "test-secret-key-for-testing"


class TestJWT:
    def test_create_and_validate(self) -> None:
        token = create_jwt_token(
            user_id="user_123",
            tenant_id="tenant_456",
            roles=["admin", "builder"],
            secret=SECRET,
        )
        ctx = validate_jwt_token(token, secret=SECRET)
        assert ctx.user_id == "user_123"
        assert ctx.tenant_id == "tenant_456"
        assert ctx.user_type == "builder"
        assert "admin" in ctx.roles

    def test_invalid_token(self) -> None:
        with pytest.raises(AuthError, match="Invalid token"):
            validate_jwt_token("not.a.valid.token", secret=SECRET)

    def test_wrong_secret(self) -> None:
        token = create_jwt_token(user_id="u1", tenant_id="t1", roles=[], secret=SECRET)
        with pytest.raises(AuthError):
            validate_jwt_token(token, secret="wrong-secret")

    def test_expired_token(self) -> None:
        token = create_jwt_token(
            user_id="u1",
            tenant_id="t1",
            roles=[],
            secret=SECRET,
            expiry_seconds=-1,  # already expired
        )
        with pytest.raises(AuthError, match="expired"):
            validate_jwt_token(token, secret=SECRET)


class TestAPIKey:
    def test_generate_format(self) -> None:
        key = generate_api_key()
        assert key.startswith("sk_live_")
        assert len(key) > 20

    def test_hash_deterministic(self) -> None:
        key = "sk_live_test123"
        h1 = hash_api_key(key)
        h2 = hash_api_key(key)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_keys_different_hashes(self) -> None:
        h1 = hash_api_key("sk_live_aaa")
        h2 = hash_api_key("sk_live_bbb")
        assert h1 != h2
