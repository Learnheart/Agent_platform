"""Message repository — conversation history persistence."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import messages


class MessageRepository:
    """PostgreSQL repository for messages."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = {**data, "tenant_id": tenant_id}
            await session.execute(messages.insert().values(**row))
            await session.commit()
            return row

    async def create_batch(self, tenant_id: str, items: list[dict[str, Any]]) -> int:
        """Batch insert messages."""
        if not items:
            return 0
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            rows = [{**item, "tenant_id": tenant_id} for item in items]
            await session.execute(messages.insert(), rows)
            await session.commit()
            return len(rows)

    async def list_by_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                messages.select()
                .where(
                    sa.and_(
                        messages.c.tenant_id == tenant_id,
                        messages.c.session_id == session_id,
                    )
                )
                .order_by(messages.c.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
            return [dict(r) for r in result.mappings().all()]

    async def count_by_session(self, tenant_id: str, session_id: str) -> int:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                sa.select(sa.func.count())
                .select_from(messages)
                .where(
                    sa.and_(
                        messages.c.tenant_id == tenant_id,
                        messages.c.session_id == session_id,
                    )
                )
            )
            return result.scalar_one()
