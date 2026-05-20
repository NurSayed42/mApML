import asyncio
import redis.asyncio as aioredis
import structlog
from typing import Optional
from core.config import settings

logger = structlog.get_logger(__name__)

_redis_client: Optional[aioredis.Redis] = None


def _normalize_redis_url(url: str) -> str:
    """Prefer IPv4 loopback on Windows to avoid localhost → ::1 hangs."""
    return url.replace("redis://localhost", "redis://127.0.0.1")


async def connect_redis() -> aioredis.Redis:
    """
    Create (if needed) and verify the shared Redis client with PING.
    Raises on connection failure instead of hanging silently on first command.
    """
    global _redis_client
    url = _normalize_redis_url(settings.redis_url)

    if _redis_client is None:
        logger.info("redis_connecting", url=url.split("@")[-1])
        _redis_client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            retry_on_timeout=False,
            health_check_interval=30,
        )

    try:
        await asyncio.wait_for(
            _redis_client.ping(),
            timeout=settings.redis_connect_timeout_seconds,
        )
    except asyncio.TimeoutError as e:
        logger.error(
            "redis_ping_timeout",
            url=url.split("@")[-1],
            timeout_seconds=settings.redis_connect_timeout_seconds,
        )
        _redis_client = None
        raise ConnectionError(
            f"Redis PING timed out after {settings.redis_connect_timeout_seconds}s "
            f"(check REDIS_URL={settings.redis_url})"
        ) from e
    except Exception as e:
        logger.error("redis_ping_failed", url=url.split("@")[-1], error=str(e))
        _redis_client = None
        raise ConnectionError(f"Redis connection failed: {e}") from e

    logger.info("redis_connected", url=url.split("@")[-1])
    return _redis_client


async def get_redis() -> aioredis.Redis:
    """Return the shared Redis client, connecting on first use."""
    if _redis_client is None:
        return await connect_redis()
    return _redis_client


class DistributedLock:
    """Redis-based distributed lock using SET NX EX pattern."""

    def __init__(self, redis: aioredis.Redis, key: str, ttl: int = settings.worker_lock_ttl_seconds):
        self.redis = redis
        self.key = f"lock:{key}"
        self.ttl = ttl
        self._acquired = False

    async def acquire(self) -> bool:
        result = await self.redis.set(self.key, "1", nx=True, ex=self.ttl)
        self._acquired = bool(result)
        return self._acquired

    async def release(self):
        if self._acquired:
            await self.redis.delete(self.key)
            self._acquired = False

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        await self.release()


async def acquire_lock(redis: aioredis.Redis, task_id: str) -> bool:
    lock = DistributedLock(redis, task_id)
    return await lock.acquire()


async def release_lock(redis: aioredis.Redis, task_id: str):
    await redis.delete(f"lock:{task_id}")