"""Agent repository — CRUD operations for agents table."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import agents


class AgentRepository:
    """PostgreSQL repository for agent definitions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            now = datetime.now(timezone.utc)
            row = {**data, "tenant_id": tenant_id, "created_at": now, "updated_at": now}
            await session.execute(agents.insert().values(**row))
            await session.commit()
            return row

    async def get(self, tenant_id: str, agent_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                agents.select().where(
                    sa.and_(agents.c.tenant_id == tenant_id, agents.c.id == agent_id)
                )
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def update(self, tenant_id: str, agent_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            data["updated_at"] = datetime.now(timezone.utc)
            await session.execute(
                agents.update()
                .where(sa.and_(agents.c.tenant_id == tenant_id, agents.c.id == agent_id))
                .values(**data)
            )
            await session.commit()
            return await self.get(tenant_id, agent_id)

    async def delete(self, tenant_id: str, agent_id: str) -> bool:
        """Soft delete — set status to 'archived'."""
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                agents.update()
                .where(sa.and_(agents.c.tenant_id == tenant_id, agents.c.id == agent_id))
                .values(status="archived", updated_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return result.rowcount > 0

    async def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List agents with cursor-based pagination."""
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            query = agents.select().where(agents.c.tenant_id == tenant_id)

            if status:
                query = query.where(agents.c.status == status)

            if cursor:
                created_at, row_id = _decode_cursor(cursor)
                query = query.where(
                    sa.or_(
                        agents.c.created_at < created_at,
                        sa.and_(agents.c.created_at == created_at, agents.c.id < row_id),
                    )
                )

            query = query.order_by(agents.c.created_at.desc(), agents.c.id.desc()).limit(limit + 1)
            result = await session.execute(query)
            rows = [dict(r) for r in result.mappings().all()]

            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            next_cursor = None
            if has_more and rows:
                last = rows[-1]
                next_cursor = _encode_cursor(last["created_at"], last["id"])

            return {"items": rows, "has_more": has_more, "next_cursor": next_cursor}


def _encode_cursor(created_at: datetime, row_id: str) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": row_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return datetime.fromisoformat(payload["created_at"]), payload["id"]
