"""Cost Tracker — accumulates and reports costs per session/agent/tenant.

See docs/architecture/09-governance.md.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import CostEvent

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks LLM and tool invocation costs.

    Accumulates costs in memory and optionally persists to
    Redis (hot) and PostgreSQL (durable).
    """

    def __init__(
        self,
        redis_cost_store: Any | None = None,  # CostRedisStore
        pg_cost_repo: Any | None = None,  # CostRepository
    ) -> None:
        self._redis = redis_cost_store
        self._pg = pg_cost_repo
        # In-memory accumulator: {session_id: total_cost_usd}
        self._session_costs: dict[str, float] = {}

    async def track(self, event: CostEvent) -> None:
        """Record a cost event."""
        # Accumulate in memory
        self._session_costs[event.session_id] = (
            self._session_costs.get(event.session_id, 0.0) + event.cost_usd
        )

        # Write to Redis (hot, best-effort)
        if self._redis is not None:
            try:
                await self._redis.track(
                    session_id=event.session_id,
                    cost_usd=event.cost_usd,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                )
            except Exception:
                logger.warning("Redis cost tracking failed", exc_info=True)

        # Write to PG (durable, best-effort)
        if self._pg is not None:
            try:
                await self._pg.insert_event(event.tenant_id, event.model_dump(mode="json"))
            except Exception:
                logger.warning("PG cost tracking failed", exc_info=True)

    def get_session_cost(self, session_id: str) -> float:
        """Get accumulated cost for a session (from memory)."""
        return self._session_costs.get(session_id, 0.0)

    def get_all_costs(self) -> dict[str, float]:
        """Get all session costs (for debugging/monitoring)."""
        return dict(self._session_costs)
