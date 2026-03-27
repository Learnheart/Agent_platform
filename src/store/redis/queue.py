"""Redis Streams task queue — producer + consumer.

Key pattern: tasks:{tenant_id} (stream)
Consumer group: executor_group
See docs/architecture/08-event-bus.md Section 3.
"""

from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis


class TaskQueue:
    """Redis Streams-based task queue."""

    CONSUMER_GROUP = "executor_group"

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def enqueue(self, tenant_id: str, task: dict[str, Any]) -> str:
        """Add a task to the stream. Returns stream entry ID."""
        stream = f"tasks:{tenant_id}"
        entry_id = await self._redis.xadd(
            stream,
            {"data": orjson.dumps(task).decode()},
        )
        return entry_id

    async def ensure_group(self, tenant_id: str) -> None:
        """Create consumer group if it doesn't exist."""
        stream = f"tasks:{tenant_id}"
        try:
            await self._redis.xgroup_create(stream, self.CONSUMER_GROUP, id="0", mkstream=True)
        except Exception:
            # Group already exists
            pass

    async def read(
        self,
        tenant_id: str,
        consumer_id: str,
        *,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read tasks from stream as consumer. Returns list of (entry_id, task_data)."""
        stream = f"tasks:{tenant_id}"
        results = await self._redis.xreadgroup(
            groupname=self.CONSUMER_GROUP,
            consumername=consumer_id,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        if not results:
            return []

        tasks = []
        for _stream_name, entries in results:
            for entry_id, fields in entries:
                task_data = orjson.loads(fields["data"])
                tasks.append((entry_id, task_data))
        return tasks

    async def ack(self, tenant_id: str, entry_id: str) -> None:
        """Acknowledge a processed task."""
        stream = f"tasks:{tenant_id}"
        await self._redis.xack(stream, self.CONSUMER_GROUP, entry_id)

    async def pending_count(self, tenant_id: str) -> int:
        """Get count of pending (unacknowledged) tasks."""
        stream = f"tasks:{tenant_id}"
        try:
            info = await self._redis.xpending(stream, self.CONSUMER_GROUP)
            return info.get("pending", 0) if isinstance(info, dict) else 0
        except Exception:
            return 0
