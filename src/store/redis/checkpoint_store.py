"""Redis checkpoint store — delta chain + snapshot cache.

Key patterns from docs/architecture/03-planning.md Section 2.6.
- checkpoint:deltas:{session_id}   (list) — delta chain
- checkpoint:snapshot:{session_id} (bytes) — latest snapshot
"""

from __future__ import annotations

from typing import Any

import msgpack
from redis.asyncio import Redis


class CheckpointRedisStore:
    """Redis-backed checkpoint hot cache."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def append_delta(self, session_id: str, delta: dict[str, Any], ttl: int = 3600) -> None:
        key = f"checkpoint:deltas:{session_id}"
        await self._redis.rpush(key, msgpack.packb(delta, default=str))
        await self._redis.expire(key, ttl)

    async def get_deltas(self, session_id: str) -> list[dict[str, Any]]:
        key = f"checkpoint:deltas:{session_id}"
        raw_list = await self._redis.lrange(key, 0, -1)
        return [msgpack.unpackb(r, raw=False) for r in raw_list]

    async def get_deltas_after(self, session_id: str, after_index: int) -> list[dict[str, Any]]:
        """Get deltas with step_index > after_index."""
        all_deltas = await self.get_deltas(session_id)
        return [d for d in all_deltas if d.get("step_index", 0) > after_index]

    async def save_snapshot(self, session_id: str, snapshot: bytes, ttl: int = 3600) -> None:
        key = f"checkpoint:snapshot:{session_id}"
        await self._redis.set(key, snapshot, ex=ttl)

    async def get_snapshot(self, session_id: str) -> bytes | None:
        key = f"checkpoint:snapshot:{session_id}"
        return await self._redis.get(key)

    async def clear_deltas(self, session_id: str) -> None:
        key = f"checkpoint:deltas:{session_id}"
        await self._redis.delete(key)

    async def delete_all(self, session_id: str) -> None:
        await self._redis.delete(
            f"checkpoint:deltas:{session_id}",
            f"checkpoint:snapshot:{session_id}",
        )
