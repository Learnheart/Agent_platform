"""Redis Pub/Sub event publisher.

Channel patterns from docs/architecture/08-event-bus.md Section 2.
- events:{session_id}  — per-session events (SSE consumer)
- events:global        — all events (OTel, Governance, Webhook)
"""

from __future__ import annotations

from redis.asyncio import Redis


class EventPublisher:
    """Redis Pub/Sub publisher for agent events."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def publish(self, channel: str, message: str) -> int:
        """Publish message to a Redis Pub/Sub channel.

        Returns number of subscribers that received the message.
        """
        return await self._redis.publish(channel, message)

    async def publish_session_event(self, session_id: str, message: str) -> None:
        """Publish to both session-specific and global channels."""
        pipe = self._redis.pipeline()
        pipe.publish(f"events:{session_id}", message)
        pipe.publish("events:global", message)
        await pipe.execute()
