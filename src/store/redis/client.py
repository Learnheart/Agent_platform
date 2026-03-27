"""Redis async client wrapper.

See docs/architecture/02-foundation.md Section 4 — RedisSettings.
"""

from __future__ import annotations

from redis.asyncio import Redis

from src.core.config import RedisSettings


def create_redis_client(settings: RedisSettings) -> Redis:  # type: ignore[type-arg]
    """Create async Redis client from settings."""
    return Redis.from_url(
        settings.url,
        max_connections=settings.max_connections,
        decode_responses=settings.decode_responses,
        socket_timeout=settings.socket_timeout,
        retry_on_timeout=settings.retry_on_timeout,
    )
