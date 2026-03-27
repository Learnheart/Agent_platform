"""Redis budget store — atomic budget counters.

Key pattern: budget:{session_id} (hash)
Fields: tokens, cost, steps, start_time
Uses atomic HINCRBY/HINCRBYFLOAT for thread-safe updates.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis


class BudgetRedisStore:
    """Redis-backed budget counters with atomic operations."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def initialize(self, session_id: str, ttl: int = 3600) -> None:
        """Initialize budget counters for a new session."""
        key = f"budget:{session_id}"
        await self._redis.hset(key, mapping={
            "tokens": "0",
            "cost": "0.0",
            "steps": "0",
            "start_time": str(time.time()),
        })
        await self._redis.expire(key, ttl)

    async def increment(
        self,
        session_id: str,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        steps: int = 0,
    ) -> dict[str, float]:
        """Atomically increment budget counters. Returns updated values."""
        key = f"budget:{session_id}"
        pipe = self._redis.pipeline()
        if tokens:
            pipe.hincrby(key, "tokens", tokens)
        if cost:
            pipe.hincrbyfloat(key, "cost", cost)
        if steps:
            pipe.hincrby(key, "steps", steps)
        await pipe.execute()
        return await self.get(session_id)

    async def get(self, session_id: str) -> dict[str, float]:
        """Get current budget counters."""
        key = f"budget:{session_id}"
        raw = await self._redis.hgetall(key)
        if not raw:
            return {"tokens": 0, "cost": 0.0, "steps": 0, "elapsed_seconds": 0.0}
        start_time = float(raw.get("start_time", time.time()))
        return {
            "tokens": int(raw.get("tokens", 0)),
            "cost": float(raw.get("cost", 0.0)),
            "steps": int(raw.get("steps", 0)),
            "elapsed_seconds": time.time() - start_time,
        }

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(f"budget:{session_id}")
