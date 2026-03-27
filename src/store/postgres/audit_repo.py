"""Audit repository — append-only audit event storage."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import audit_events


class AuditRepository:
    """PostgreSQL repository for audit events (append-only)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def batch_insert(self, events: list[dict[str, Any]]) -> int:
        """Batch insert audit events."""
        if not events:
            return 0
        async with self._session_factory() as session:
            await session.execute(audit_events.insert(), events)
            await session.commit()
            return len(events)

    async def query(
        self,
        tenant_id: str,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        category: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            query = audit_events.select().where(audit_events.c.tenant_id == tenant_id)

            if session_id:
                query = query.where(audit_events.c.session_id == session_id)
            if agent_id:
                query = query.where(audit_events.c.agent_id == agent_id)
            if category:
                query = query.where(audit_events.c.category == category)
            if outcome:
                query = query.where(audit_events.c.outcome == outcome)

            query = query.order_by(audit_events.c.timestamp.desc()).limit(limit).offset(offset)
            result = await session.execute(query)
            return [dict(r) for r in result.mappings().all()]
