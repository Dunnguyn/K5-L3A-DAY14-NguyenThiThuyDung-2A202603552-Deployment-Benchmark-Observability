"""Redis clients are created per worker and connect lazily."""

from redis import Redis
from redis.exceptions import RedisError

from .config import settings


def create_redis_client() -> Redis:
    try:
        return Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    except ValueError:
        raise ValueError("Invalid REDIS_URL configuration") from None


def redis_healthy(client: Redis) -> bool:
    try:
        return bool(client.ping())
    except RedisError:
        return False
