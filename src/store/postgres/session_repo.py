"""Session repository — CRUD + state management for sessions table."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import sessions


class SessionRepository:
    """PostgreSQL repository for sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            now = datetime.now(timezone.utc)
            row = {**data, "tenant_id": tenant_id, "created_at": now, "updated_at": now}
            # Map 'metadata' to 'metadata_' column
            if "metadata" in row:
                row["metadata_"] = row.pop("metadata")
            await session.execute(sessions.insert().values(**row))
            await session.commit()
            return row

    async def get(self, tenant_id: str, session_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                sessions.select().where(
                    sa.and_(sessions.c.tenant_id == tenant_id, sessions.c.id == session_id)
                )
            )
            row = result.mappings().first()
            if row is None:
                return None
            d = dict(row)
            if "metadata_" in d:
                d["metadata"] = d.pop("metadata_")
            return d

    async def update_state(
        self,
        tenant_id: str,
        session_id: str,
        state: str,
        *,
        step_index: int | None = None,
        usage: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            values: dict[str, Any] = {
                "state": state,
                "updated_at": datetime.now(timezone.utc),
            }
            if step_index is not None:
                values["step_index"] = step_index
            if usage is not None:
                values["usage"] = usage
            if completed_at is not None:
                values["completed_at"] = completed_at

            result = await session.execute(
                sessions.update()
                .where(sa.and_(sessions.c.tenant_id == tenant_id, sessions.c.id == session_id))
                .values(**values)
            )
            await session.commit()
            return result.rowcount > 0

    async def list(
        self,
        tenant_id: str,
        *,
        agent_id: str | None = None,
        state: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            query = sessions.select().where(sessions.c.tenant_id == tenant_id)

            if agent_id:
                query = query.where(sessions.c.agent_id == agent_id)
            if state:
                query = query.where(sessions.c.state == state)

            if cursor:
                payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                created_at = datetime.fromisoformat(payload["created_at"])
                row_id = payload["id"]
                query = query.where(
                    sa.or_(
                        sessions.c.created_at < created_at,
                        sa.and_(sessions.c.created_at == created_at, sessions.c.id < row_id),
                    )
                )

            query = query.order_by(sessions.c.created_at.desc(), sessions.c.id.desc()).limit(limit + 1)
            result = await session.execute(query)
            rows = []
            for r in result.mappings().all():
                d = dict(r)
                if "metadata_" in d:
                    d["metadata"] = d.pop("metadata_")
                rows.append(d)

            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            next_cursor = None
            if has_more and rows:
                last = rows[-1]
                payload = json.dumps({"created_at": last["created_at"].isoformat(), "id": last["id"]})
                next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

            return {"items": rows, "has_more": has_more, "next_cursor": next_cursor}
