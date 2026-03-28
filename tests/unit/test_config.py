"""Tests for configuration loading."""

import os
from unittest.mock import patch

from src.core.config import (
    AuthSettings,
    DatabaseSettings,
    GovernanceSettings,
    LLMSettings,
    RedisSettings,
    Settings,
    TracingSettings,
)


class TestDatabaseSettings:
    def test_dsn_property(self) -> None:
        db = DatabaseSettings(host="db.example.com", port=5432, name="mydb", user="admin", password="secret")
        assert db.dsn == "postgresql+asyncpg://admin:secret@db.example.com:5432/mydb"

    def test_defaults(self) -> None:
        db = DatabaseSettings()
        assert db.host == "localhost"
        assert db.pool_min_size == 5
        assert db.pool_max_size == 20


class TestRedisSettings:
    def test_defaults(self) -> None:
        r = RedisSettings()
        assert r.url == "redis://localhost:6379/0"
        assert r.max_connections == 50


class TestLLMSettings:
    def test_defaults(self) -> None:
        llm = LLMSettings()
        assert llm.default_model == "claude-sonnet-4-5-20250514"
        assert llm.default_timeout == 120.0


class TestAuthSettings:
    def test_defaults(self) -> None:
        auth = AuthSettings()
        assert auth.jwt_algorithm == "HS256"
        assert auth.jwt_issuer == "agent-platform"


class TestTracingSettings:
    def test_defaults(self) -> None:
        t = TracingSettings()
        assert t.enabled is True
        assert t.exporter == "otlp"


class TestGovernanceSettings:
    def test_defaults(self) -> None:
        g = GovernanceSettings()
        assert g.audit_enabled is True
        assert g.audit_buffer_size == 1000


class TestSettings:
    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            s = Settings(_env_file=None)
            assert s.app_name == "agent-platform"
            assert s.environment == "development"
            assert s.debug is False

    def test_env_override(self) -> None:
        env = {
            "APP_ENVIRONMENT": "production",
            "APP_DEBUG": "true",
            "APP_LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)
            assert s.environment == "production"
            assert s.debug is True
            assert s.log_level == "DEBUG"

    def test_nested_env_override(self) -> None:
        env = {
            "APP_DATABASE__HOST": "prod-db.example.com",
            "APP_DATABASE__PORT": "5433",
            "APP_DATABASE__PASSWORD": "prod-secret",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)
            assert s.database.host == "prod-db.example.com"
            assert s.database.port == 5433
            assert s.database.password == "prod-secret"
