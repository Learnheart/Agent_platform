"""Tool repository — tool registry persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import mcp_servers, tools


class ToolRepository:
    """PostgreSQL repository for tool registry."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # --- Tools ---

    async def register_tool(self, tenant_id: str, data: dict[str, Any]) -> None:
        """Register or update a tool."""
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = {**data, "tenant_id": tenant_id}
            stmt = (
                sa.dialects.postgresql.insert(tools)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "id"],
                    set_={k: v for k, v in row.items() if k not in ("tenant_id", "id")},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def unregister_tool(self, tenant_id: str, tool_id: str) -> bool:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                tools.delete().where(
                    sa.and_(tools.c.tenant_id == tenant_id, tools.c.id == tool_id)
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_tool(self, tenant_id: str, tool_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                tools.select().where(
                    sa.and_(tools.c.tenant_id == tenant_id, tools.c.id == tool_id)
                )
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def list_by_tenant(self, tenant_id: str, *, status: str = "active") -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                tools.select()
                .where(sa.and_(tools.c.tenant_id == tenant_id, tools.c.status == status))
                .order_by(tools.c.namespace, tools.c.name)
            )
            return [dict(r) for r in result.mappings().all()]

    async def list_by_namespace(self, tenant_id: str, namespace: str) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                tools.select().where(
                    sa.and_(tools.c.tenant_id == tenant_id, tools.c.namespace == namespace)
                )
            )
            return [dict(r) for r in result.mappings().all()]

    async def update_status(self, tenant_id: str, tool_id: str, status: str) -> None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            await session.execute(
                tools.update()
                .where(sa.and_(tools.c.tenant_id == tenant_id, tools.c.id == tool_id))
                .values(status=status, last_verified_at=datetime.now(timezone.utc))
            )
            await session.commit()

    # --- MCP Servers ---

    async def create_server(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = {**data, "tenant_id": tenant_id}
            await session.execute(mcp_servers.insert().values(**row))
            await session.commit()
            return row

    async def get_server(self, tenant_id: str, server_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                mcp_servers.select().where(
                    sa.and_(mcp_servers.c.tenant_id == tenant_id, mcp_servers.c.id == server_id)
                )
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def list_servers(self, tenant_id: str) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                mcp_servers.select()
                .where(mcp_servers.c.tenant_id == tenant_id)
                .order_by(mcp_servers.c.name)
            )
            return [dict(r) for r in result.mappings().all()]

    async def delete_server(self, tenant_id: str, server_id: str) -> bool:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                mcp_servers.delete().where(
                    sa.and_(mcp_servers.c.tenant_id == tenant_id, mcp_servers.c.id == server_id)
                )
            )
            await session.commit()
            return result.rowcount > 0
