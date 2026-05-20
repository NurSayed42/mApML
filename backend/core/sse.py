import json
import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
import structlog
from core.locks import get_redis

logger = structlog.get_logger(__name__)

EVENT_SCHEMA_VERSION = "v1"


def build_event(
    event_type: str,
    task_id: str,
    correlation_id: str,
    data: dict,
) -> dict:
    return {
        "event_type": event_type,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


async def push_sse_event(user_id: str, event: dict):
    """Push event to user's SSE Redis channel."""
    redis = await get_redis()
    channel = f"sse_events_{user_id}"
    await redis.rpush(channel, json.dumps(event))
    await redis.expire(channel, 3600)  # 1 hour TTL


async def stream_sse_events(user_id: str, task_id: str) -> AsyncGenerator[str, None]:
    """
    Async generator that reads SSE events from Redis for a specific task.
    Yields SSE-formatted strings.
    """
    redis = await get_redis()
    channel = f"sse_events_{user_id}"
    last_index = 0

    # Send heartbeat to keep connection alive
    yield "data: {\"event_type\": \"connected\"}\n\n"

    timeout_count = 0
    max_timeouts = 300  # 5 minutes of inactivity

    while timeout_count < max_timeouts:
        try:
            # Use LRANGE to get new events since last_index
            messages = await redis.lrange(channel, last_index, -1)
            if messages:
                for msg in messages:
                    last_index += 1
                    try:
                        event = json.loads(msg)
                        if event.get("task_id") == task_id:
                            yield f"data: {json.dumps(event)}\n\n"
                            if event.get("event_type") in ("task_completed", "task_failed"):
                                return
                        timeout_count = 0
                    except json.JSONDecodeError:
                        continue
            else:
                timeout_count += 1
                # Heartbeat every 15 seconds
                if timeout_count % 15 == 0:
                    yield ": heartbeat\n\n"

            await asyncio.sleep(1)

        except Exception as e:
            logger.error("sse_stream_error", error=str(e), user_id=user_id, task_id=task_id)
            yield f"data: {{\"event_type\": \"error\", \"message\": \"Stream error\"}}\n\n"
            return
