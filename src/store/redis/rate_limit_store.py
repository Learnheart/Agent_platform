"""Redis rate limit store — token bucket via Lua script.

Key pattern: rate_limit:{scope}:{key}
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

# Lua script for atomic token bucket check-and-decrement
_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = max_tokens
    last_refill = now
end

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local refill = elapsed * refill_rate
tokens = math.min(max_tokens, tokens + refill)

-- Try to consume one token
if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 0
end
"""


class RateLimitRedisStore:
    """Redis-backed rate limiter using token bucket algorithm."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._script = self._redis.register_script(_RATE_LIMIT_SCRIPT)

    async def check_and_consume(
        self,
        scope: str,
        key: str,
        *,
        max_tokens: int = 60,
        refill_rate: float = 1.0,
    ) -> bool:
        """Check rate limit and consume one token. Returns True if allowed."""
        redis_key = f"rate_limit:{scope}:{key}"
        result = await self._script(
            keys=[redis_key],
            args=[max_tokens, refill_rate, time.time()],
        )
        return bool(result)

    async def get_remaining(self, scope: str, key: str) -> int:
        """Get remaining tokens (approximate)."""
        redis_key = f"rate_limit:{scope}:{key}"
        tokens = await self._redis.hget(redis_key, "tokens")
        return int(float(tokens)) if tokens else 0

    async def reset(self, scope: str, key: str) -> None:
        redis_key = f"rate_limit:{scope}:{key}"
        await self._redis.delete(redis_key)
