"""Redis cost store — real-time cost accumulators.

Key pattern: cost:{scope}:{id}:daily:{date}
"""

from __future__ import annotations

from datetime import date

from redis.asyncio import Redis


class CostRedisStore:
    """Redis-backed real-time cost accumulators."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def track(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        session_id: str,
        cost_usd: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Track cost across multiple scopes atomically."""
        today = date.today().isoformat()
        pipe = self._redis.pipeline()

        # Per-session accumulator
        session_key = f"cost:session:{session_id}"
        pipe.hincrbyfloat(session_key, "cost_usd", cost_usd)
        pipe.hincrby(session_key, "input_tokens", input_tokens)
        pipe.hincrby(session_key, "output_tokens", output_tokens)
        pipe.hincrby(session_key, "call_count", 1)
        pipe.expire(session_key, 86400)

        # Per-agent daily
        agent_key = f"cost:agent:{agent_id}:daily:{today}"
        pipe.hincrbyfloat(agent_key, "cost_usd", cost_usd)
        pipe.hincrby(agent_key, "call_count", 1)
        pipe.expire(agent_key, 172800)  # 2 days

        # Per-tenant daily
        tenant_key = f"cost:tenant:{tenant_id}:daily:{today}"
        pipe.hincrbyfloat(tenant_key, "cost_usd", cost_usd)
        pipe.hincrby(tenant_key, "call_count", 1)
        pipe.expire(tenant_key, 172800)

        await pipe.execute()

    async def get_session_cost(self, session_id: str) -> dict[str, float]:
        key = f"cost:session:{session_id}"
        raw = await self._redis.hgetall(key)
        if not raw:
            return {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "call_count": 0}
        return {
            "cost_usd": float(raw.get("cost_usd", 0)),
            "input_tokens": int(raw.get("input_tokens", 0)),
            "output_tokens": int(raw.get("output_tokens", 0)),
            "call_count": int(raw.get("call_count", 0)),
        }

    async def get_tenant_daily_cost(self, tenant_id: str, day: date | None = None) -> float:
        day = day or date.today()
        key = f"cost:tenant:{tenant_id}:daily:{day.isoformat()}"
        raw = await self._redis.hget(key, "cost_usd")
        return float(raw) if raw else 0.0
