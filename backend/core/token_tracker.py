import json
import asyncio
import time
from typing import Dict
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from models.database import TokenUsage, AsyncSessionLocal
from core.locks import get_redis
from core.config import settings
from core.uuid_utils import parse_uuid

logger = structlog.get_logger(__name__)

TOKEN_BUFFER_KEY = "token_usage_buffer"


async def log_token_usage(
    task_id: str,
    dag_node_id: str,
    user_id: str,
    correlation_id: str,
    agent_name: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
):
    """Add token usage record to Redis buffer."""
    redis = await get_redis()
    record = {
        "task_id": task_id,
        "dag_node_id": dag_node_id,
        "user_id": user_id,
        "correlation_id": correlation_id,
        "agent_name": agent_name,
        "model_name": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "timestamp": time.time(),
    }
    await redis.rpush(TOKEN_BUFFER_KEY, json.dumps(record))

    # Check if we should flush
    buffer_length = await redis.llen(TOKEN_BUFFER_KEY)
    if buffer_length >= settings.token_buffer_flush_count:
        await flush_token_buffer()


async def flush_token_buffer():
    """Flush token usage buffer to PostgreSQL."""
    redis = await get_redis()
    records = []

    # Atomically pull all records
    while True:
        raw = await redis.lpop(TOKEN_BUFFER_KEY)
        if raw is None:
            break
        try:
            records.append(json.loads(raw))
        except Exception:
            pass

    if not records:
        return

    try:
        async with AsyncSessionLocal() as db:
            for r in records:
                usage = TokenUsage(
                    task_id=parse_uuid(r["task_id"]),
                    dag_node_id=parse_uuid(r.get("dag_node_id")),
                    user_id=parse_uuid(r["user_id"]),
                    correlation_id=parse_uuid(r["correlation_id"]),
                    agent_name=r["agent_name"],
                    model_name=r["model_name"],
                    prompt_tokens=r["prompt_tokens"],
                    completion_tokens=r["completion_tokens"],
                    total_tokens=r["total_tokens"],
                )
                db.add(usage)
            await db.commit()
            logger.info("token_buffer_flushed", count=len(records))
    except Exception as e:
        logger.error("token_buffer_flush_failed", error=str(e))
        # Re-queue records on failure
        for r in records:
            await redis.rpush(TOKEN_BUFFER_KEY, json.dumps(r))


async def periodic_flush():
    """Flush token buffer every 30 seconds regardless of count."""
    while True:
        await asyncio.sleep(settings.token_buffer_flush_seconds)
        try:
            await flush_token_buffer()
        except Exception as e:
            logger.error("periodic_flush_error", error=str(e))


# ─── Gemini RPM Rate Limiter ─────────────────────────────────────
GEMINI_RPM_COUNTER_KEY = "gemini_rpm_counter"
GEMINI_RPM_WINDOW = 60  # seconds


async def check_and_increment_gemini_rpm() -> bool:
    """
    Returns True if API call is allowed.
    Returns False if approaching rate limit (>= buffer threshold).
    """
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.incr(GEMINI_RPM_COUNTER_KEY)
    pipe.expire(GEMINI_RPM_COUNTER_KEY, GEMINI_RPM_WINDOW)
    results = await pipe.execute()
    current_count = results[0]

    if current_count >= settings.gemini_rpm_buffer:
        logger.warning(
            "gemini_rpm_limit_approached",
            current_count=current_count,
            limit=settings.gemini_rpm_limit,
        )
        return False
    return True


async def wait_for_gemini_slot(max_wait: int = 60):
    """Wait until a Gemini RPM slot is available."""
    for _ in range(max_wait):
        allowed = await check_and_increment_gemini_rpm()
        if allowed:
            return
        await asyncio.sleep(1)
    raise TimeoutError("Gemini RPM rate limit wait timed out")


# ─── Tavily Request Counter ──────────────────────────────────────
TAVILY_COUNTER_KEY = "tavily_monthly_counter"


async def increment_tavily_counter() -> int:
    redis = await get_redis()
    count = await redis.incr(TAVILY_COUNTER_KEY)
    # Set TTL to 32 days if newly created
    ttl = await redis.ttl(TAVILY_COUNTER_KEY)
    if ttl == -1:
        await redis.expire(TAVILY_COUNTER_KEY, 32 * 24 * 3600)
    return count


async def get_tavily_count() -> int:
    redis = await get_redis()
    val = await redis.get(TAVILY_COUNTER_KEY)
    return int(val) if val else 0


# ─── Resend Daily Counter ────────────────────────────────────────
RESEND_COUNTER_KEY = "resend_daily_counter"


async def increment_resend_counter() -> int:
    redis = await get_redis()
    count = await redis.incr(RESEND_COUNTER_KEY)
    ttl = await redis.ttl(RESEND_COUNTER_KEY)
    if ttl == -1:
        await redis.expire(RESEND_COUNTER_KEY, 24 * 3600)
    return count


async def get_resend_count() -> int:
    redis = await get_redis()
    val = await redis.get(RESEND_COUNTER_KEY)
    return int(val) if val else 0
