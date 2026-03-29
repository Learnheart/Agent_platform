"""E2E test fixtures — real PostgreSQL + Redis from SC infrastructure."""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.api.app import create_app
from src.core.config import get_settings
from src.core.security import create_jwt_token
from src.store.postgres.database import create_engine, create_session_factory
from src.store.postgres.models import (
    agents,
    messages,
    sessions,
    tenants,
)
from src.store.redis.client import create_redis_client

# Unique tenant per test module run
_TEST_TENANT_ID = f"e2e_tenant_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Database (function-scoped to avoid event loop issues)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine() -> AsyncEngine:
    settings = get_settings()
    return create_engine(settings.database)


@pytest.fixture
def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

@pytest.fixture
def redis_client() -> Redis:  # type: ignore[type-arg]
    settings = get_settings()
    return create_redis_client(settings.redis)


# ---------------------------------------------------------------------------
# Test tenant — isolated data per test run
# ---------------------------------------------------------------------------

@pytest.fixture
def test_tenant_id() -> str:
    return _TEST_TENANT_ID


@pytest.fixture(autouse=True)
async def setup_test_tenant(
    db_session_factory: async_sessionmaker[AsyncSession],
    test_tenant_id: str,
) -> AsyncGenerator[None, None]:
    """Insert test tenant before each test, clean up after."""
    async with db_session_factory() as session:
        result = await session.execute(
            tenants.select().where(tenants.c.id == test_tenant_id)
        )
        if result.first() is None:
            await session.execute(
                tenants.insert().values(
                    id=test_tenant_id,
                    name="E2E Test Tenant",
                    slug=f"e2e-{test_tenant_id}",
                )
            )
            await session.commit()

    yield

    # Cleanup in correct FK order
    async with db_session_factory() as session:
        for table in [messages, sessions, agents]:
            await session.execute(
                table.delete().where(table.c.tenant_id == test_tenant_id)
            )
        await session.execute(
            tenants.delete().where(tenants.c.id == test_tenant_id)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def builder_token(test_tenant_id: str) -> str:
    return create_jwt_token(
        user_id="e2e_builder",
        tenant_id=test_tenant_id,
        roles=["admin"],
        secret="dev-secret",
    )


@pytest.fixture
def builder_headers(builder_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {builder_token}"}


@pytest.fixture
def api_key_headers(test_tenant_id: str) -> dict[str, str]:
    return {"X-API-Key": f"apt_{test_tenant_id}_e2ekey"}


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
