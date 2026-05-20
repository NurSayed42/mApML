import asyncio
import json
from datetime import datetime, timezone
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from models.database import Outbox, AsyncSessionLocal
from core.locks import get_redis
from core.uuid_utils import parse_uuid

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 2


async def publish_outbox_records():
    """
    Polls unprocessed outbox records and publishes them to Redis.
    Runs every 2 seconds. Handles Redis unavailability gracefully.
    """
    while True:
        try:
            async with AsyncSessionLocal() as db:
                redis = await get_redis()
                result = await db.execute(
                    select(Outbox)
                    .where(Outbox.is_published == False)
                    .order_by(Outbox.created_at)
                    .limit(50)
                )
                records = result.scalars().all()

                for record in records:
                    try:
                        await redis.rpush(record.redis_channel, json.dumps(record.message_json))
                        record.is_published = True
                        record.published_at = datetime.now(timezone.utc)
                        logger.info(
                            "outbox_record_published",
                            outbox_id=str(record.id),
                            channel=record.redis_channel,
                            correlation_id=str(record.correlation_id),
                        )
                    except Exception as e:
                        logger.error(
                            "outbox_publish_failed",
                            outbox_id=str(record.id),
                            error=str(e),
                        )

                await db.commit()

        except Exception as e:
            logger.error("outbox_poll_error", error=str(e))

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def create_outbox_record(
    db: AsyncSession,
    task_id: str,
    correlation_id: str,
    redis_channel: str,
    message: dict,
):
    """Creates an outbox record within an existing transaction."""
    record = Outbox(
        task_id=parse_uuid(task_id),
        correlation_id=parse_uuid(correlation_id),
        redis_channel=redis_channel,
        message_json=message,
        is_published=False,
    )
    db.add(record)
    # Don't commit - caller controls transaction
    return record
