"""Redis session store — conversation buffer + working memory.

Key patterns from docs/architecture/05-memory.md Section 3.
- session:{session_id}:messages  (list) — conversation buffer
- session:{session_id}:working   (hash) — working memory
- session:{session_id}:summary   (string) — current summary
"""

from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis


class SessionRedisStore:
    """Redis-backed session hot state."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    # --- Conversation Buffer ---

    async def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        key = f"session:{session_id}:messages"
        await self._redis.rpush(key, orjson.dumps(message).decode())

    async def append_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        key = f"session:{session_id}:messages"
        encoded = [orjson.dumps(m).decode() for m in messages]
        await self._redis.rpush(key, *encoded)

    async def get_all_messages(self, session_id: str) -> list[dict[str, Any]]:
        key = f"session:{session_id}:messages"
        raw = await self._redis.lrange(key, 0, -1)
        return [orjson.loads(r) for r in raw]

    async def get_recent_messages(self, session_id: str, n: int) -> list[dict[str, Any]]:
        key = f"session:{session_id}:messages"
        raw = await self._redis.lrange(key, -n, -1)
        return [orjson.loads(r) for r in raw]

    async def get_message_count(self, session_id: str) -> int:
        key = f"session:{session_id}:messages"
        return await self._redis.llen(key)

    # --- Summary ---

    async def get_summary(self, session_id: str) -> str | None:
        key = f"session:{session_id}:summary"
        return await self._redis.get(key)

    async def set_summary(self, session_id: str, summary: str) -> None:
        key = f"session:{session_id}:summary"
        await self._redis.set(key, summary)

    # --- Working Memory ---

    async def get_working_memory(self, session_id: str) -> dict[str, Any]:
        key = f"session:{session_id}:working"
        raw = await self._redis.hgetall(key)
        return {k: orjson.loads(v) if isinstance(v, (str, bytes)) else v for k, v in raw.items()}

    async def set_working_field(self, session_id: str, field: str, value: Any) -> None:
        key = f"session:{session_id}:working"
        await self._redis.hset(key, field, orjson.dumps(value).decode())

    async def get_working_field(self, session_id: str, field: str) -> Any | None:
        key = f"session:{session_id}:working"
        raw = await self._redis.hget(key, field)
        if raw is None:
            return None
        return orjson.loads(raw)

    # --- TTL ---

    async def set_session_ttl(self, session_id: str, ttl_seconds: int) -> None:
        """Set TTL on all session keys."""
        for suffix in ("messages", "working", "summary"):
            key = f"session:{session_id}:{suffix}"
            await self._redis.expire(key, ttl_seconds)

    # --- Cleanup ---

    async def delete_session(self, session_id: str) -> None:
        keys = [f"session:{session_id}:{s}" for s in ("messages", "working", "summary")]
        await self._redis.delete(*keys)
