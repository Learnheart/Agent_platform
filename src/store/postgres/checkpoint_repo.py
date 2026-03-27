"""Checkpoint repository — delta + snapshot persistence."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import checkpoints_deltas, checkpoints_snapshots


class CheckpointRepository:
    """PostgreSQL repository for checkpoint data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_delta(self, tenant_id: str, data: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = {**data, "tenant_id": tenant_id}
            await session.execute(checkpoints_deltas.insert().values(**row))
            await session.commit()

    async def upsert_snapshot(self, tenant_id: str, data: dict[str, Any]) -> None:
        """Insert or update snapshot for a session + step_index."""
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = {**data, "tenant_id": tenant_id}
            # Try insert, on conflict update
            stmt = (
                sa.dialects.postgresql.insert(checkpoints_snapshots)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "session_id", "step_index"],
                    set_={
                        "state": row["state"],
                        "conversation_hash": row["conversation_hash"],
                        "usage": row["usage"],
                        "created_at": row.get("created_at", sa.func.now()),
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get_latest_snapshot(
        self, tenant_id: str, session_id: str
    ) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                checkpoints_snapshots.select()
                .where(
                    sa.and_(
                        checkpoints_snapshots.c.tenant_id == tenant_id,
                        checkpoints_snapshots.c.session_id == session_id,
                    )
                )
                .order_by(checkpoints_snapshots.c.step_index.desc())
                .limit(1)
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def get_deltas_after(
        self, tenant_id: str, session_id: str, after_step: int
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                checkpoints_deltas.select()
                .where(
                    sa.and_(
                        checkpoints_deltas.c.tenant_id == tenant_id,
                        checkpoints_deltas.c.session_id == session_id,
                        checkpoints_deltas.c.step_index > after_step,
                    )
                )
                .order_by(checkpoints_deltas.c.step_index.asc())
            )
            return [dict(r) for r in result.mappings().all()]

    async def delete_deltas(self, tenant_id: str, session_id: str, up_to_step: int) -> int:
        """Delete applied deltas up to a step index (after snapshot)."""
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                checkpoints_deltas.delete().where(
                    sa.and_(
                        checkpoints_deltas.c.tenant_id == tenant_id,
                        checkpoints_deltas.c.session_id == session_id,
                        checkpoints_deltas.c.step_index <= up_to_step,
                    )
                )
            )
            await session.commit()
            return result.rowcount
