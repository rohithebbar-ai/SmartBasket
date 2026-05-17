from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _pool


def get_redis_client() -> aioredis.Redis:
    """
    Returns a Redis client backed by the shared connection pool.
    Safe to call repeatedly — the pool is created once at first use.
    Use get_redis() as a FastAPI dependency instead of calling this directly in routes.
    """
    return aioredis.Redis(connection_pool=_get_pool())


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency — yields a Redis client from the shared pool."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def ping() -> bool:
    """Returns True if Redis is reachable. Used by the health endpoint."""
    try:
        client = get_redis_client()
        return await client.ping()
    except Exception:
        return False


async def close_pool() -> None:
    """Drain the connection pool during application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
