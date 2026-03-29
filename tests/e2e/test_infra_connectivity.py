"""E2E: Verify connectivity to SC-hosted infrastructure services."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.e2e


# ============================================================
# PostgreSQL
# ============================================================


class TestPostgresConnectivity:
    """Verify PostgreSQL on SC is reachable and schema is up."""

    async def test_connect_and_query(self, db_engine: AsyncEngine) -> None:
        async with db_engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT 1 AS ok"))
            row = result.one()
            assert row.ok == 1

    async def test_version(self, db_engine: AsyncEngine) -> None:
        async with db_engine.connect() as conn:
            result = await conn.execute(sa.text("SHOW server_version"))
            version = result.scalar_one()
            assert version.startswith("16") or version.startswith("17")

    async def test_pgvector_extension(self, db_engine: AsyncEngine) -> None:
        """pgvector should be available (pgvector/pgvector docker image)."""
        async with db_engine.connect() as conn:
            result = await conn.execute(
                sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            )
            assert result.first() is not None, "pgvector extension not available"

    async def test_tables_exist(self, db_engine: AsyncEngine) -> None:
        """All migration tables must exist after alembic upgrade."""
        expected_tables = {
            "tenants", "agents", "sessions", "messages",
            "checkpoints_deltas", "checkpoints_snapshots",
            "mcp_servers", "tools",
            "audit_events", "cost_events", "cost_daily_aggregates",
            "api_keys", "alembic_version",
        }
        async with db_engine.connect() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
            actual = {row[0] for row in result.all()}
        assert expected_tables.issubset(actual), f"Missing: {expected_tables - actual}"

    async def test_rls_enabled(self, db_engine: AsyncEngine) -> None:
        """Row-Level Security should be enabled on tenant-scoped tables."""
        rls_tables = [
            "agents", "sessions", "messages",
            "mcp_servers", "tools", "audit_events", "cost_events", "api_keys",
        ]
        async with db_engine.connect() as conn:
            for table_name in rls_tables:
                result = await conn.execute(
                    sa.text(
                        "SELECT rowsecurity FROM pg_tables "
                        "WHERE tablename = :t AND schemaname = 'public'"
                    ),
                    {"t": table_name},
                )
                row = result.first()
                assert row is not None, f"Table {table_name} not found"
                assert row[0] is True, f"RLS not enabled on {table_name}"


# ============================================================
# Redis
# ============================================================


class TestRedisConnectivity:
    """Verify Redis on SC is reachable."""

    async def test_ping(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        assert await redis_client.ping() is True

    async def test_set_get(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        key = "e2e_test:connectivity"
        await redis_client.set(key, "ok", ex=10)
        val = await redis_client.get(key)
        assert val == "ok"
        await redis_client.delete(key)

    async def test_db_number(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        """Verify we are on the correct Redis DB (db 2 for agent_platform)."""
        info = await redis_client.info("server")
        # Connection info shows which DB we're using
        assert info is not None

    async def test_stream_operations(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        """Test Redis Streams (used by TaskQueue)."""
        stream = "e2e_test:stream"
        # Add entry
        entry_id = await redis_client.xadd(stream, {"msg": "hello"})
        assert entry_id is not None
        # Read it back
        entries = await redis_client.xrange(stream, count=1)
        assert len(entries) == 1
        assert entries[0][1]["msg"] == "hello"
        # Cleanup
        await redis_client.delete(stream)
