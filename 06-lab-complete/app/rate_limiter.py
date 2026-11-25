"""Atomic Redis sliding-window rate limit per API key."""

from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException
from redis import Redis

from .config import settings

WINDOW_MS = 60_000

CHECK_RATE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local window = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


def check_rate_limit(client: Redis, key: str) -> None:
    digest = sha256(key.encode()).hexdigest()
    retry_after = client.eval(
        CHECK_RATE, 1, f"day14:rate:{digest}",
        WINDOW_MS, settings.rate_limit_per_minute, uuid4().hex,
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
