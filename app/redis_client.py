import redis.asyncio as aioredis

from app.config import get_settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        s = get_settings()
        _redis = aioredis.Redis(
            host=s.redis_host,
            port=s.redis_port,
            password=s.redis_password or None,
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=5,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
