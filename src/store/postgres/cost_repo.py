"""Cost repository — cost event storage and aggregation."""

from __future__ import annotations

from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.database import set_tenant_context
from src.store.postgres.models import cost_daily_aggregates, cost_events


class CostRepository:
    """PostgreSQL repository for cost tracking."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert_event(self, data: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await session.execute(cost_events.insert().values(**data))
            await session.commit()

    async def insert_events_batch(self, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        async with self._session_factory() as session:
            await session.execute(cost_events.insert(), events)
            await session.commit()
            return len(events)

    async def aggregate_by_session(self, tenant_id: str, session_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                sa.select(
                    sa.func.sum(cost_events.c.cost_usd).label("total_cost_usd"),
                    sa.func.sum(cost_events.c.input_tokens).label("total_input_tokens"),
                    sa.func.sum(cost_events.c.output_tokens).label("total_output_tokens"),
                    sa.func.count().label("total_events"),
                )
                .where(
                    sa.and_(
                        cost_events.c.tenant_id == tenant_id,
                        cost_events.c.session_id == session_id,
                    )
                )
            )
            row = result.mappings().first()
            return dict(row) if row else {}

    async def upsert_daily_aggregate(self, data: dict[str, Any]) -> None:
        """Insert or update daily cost aggregate."""
        async with self._session_factory() as session:
            stmt = (
                sa.dialects.postgresql.insert(cost_daily_aggregates)
                .values(**data)
                .on_conflict_do_update(
                    index_elements=["date", "tenant_id", "agent_id", "provider", "model"],
                    set_={
                        "total_cost_usd": cost_daily_aggregates.c.total_cost_usd + data.get("total_cost_usd", 0),
                        "total_llm_calls": cost_daily_aggregates.c.total_llm_calls + data.get("total_llm_calls", 0),
                        "total_tool_calls": cost_daily_aggregates.c.total_tool_calls + data.get("total_tool_calls", 0),
                        "total_input_tokens": cost_daily_aggregates.c.total_input_tokens + data.get("total_input_tokens", 0),
                        "total_output_tokens": cost_daily_aggregates.c.total_output_tokens + data.get("total_output_tokens", 0),
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get_daily_report(
        self,
        tenant_id: str,
        start_date: date,
        end_date: date,
        *,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            query = (
                cost_daily_aggregates.select()
                .where(
                    sa.and_(
                        cost_daily_aggregates.c.tenant_id == tenant_id,
                        cost_daily_aggregates.c.date >= start_date,
                        cost_daily_aggregates.c.date <= end_date,
                    )
                )
            )
            if agent_id:
                query = query.where(cost_daily_aggregates.c.agent_id == agent_id)

            query = query.order_by(cost_daily_aggregates.c.date.desc())
            result = await session.execute(query)
            return [dict(r) for r in result.mappings().all()]
