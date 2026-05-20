import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from core.outbox import create_outbox_record, publish_outbox_records


@pytest.mark.asyncio
async def test_create_outbox_record():
    """Test outbox record creation."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    record = await create_outbox_record(
        db=mock_db,
        task_id="task-123",
        correlation_id="corr-456",
        redis_channel="planner_tasks",
        message={"test": "data"},
    )

    mock_db.add.assert_called_once()
    assert record.task_id == "task-123"
    assert record.redis_channel == "planner_tasks"
    assert record.is_published is False
    assert record.message_json == {"test": "data"}


@pytest.mark.asyncio
async def test_publish_outbox_records_success():
    """Test that outbox records are published to Redis and marked published."""
    from models.database import Outbox
    import uuid
    from datetime import datetime, timezone

    mock_record = MagicMock(spec=Outbox)
    mock_record.id = uuid.uuid4()
    mock_record.redis_channel = "planner_tasks"
    mock_record.message_json = {"task_id": "task-123"}
    mock_record.correlation_id = uuid.uuid4()
    mock_record.is_published = False

    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_record]
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    with patch("core.outbox.AsyncSessionLocal") as mock_session, \
         patch("core.outbox.get_redis", new_callable=AsyncMock, return_value=mock_redis), \
         patch("asyncio.sleep", side_effect=StopAsyncIteration):

        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        try:
            await publish_outbox_records()
        except StopAsyncIteration:
            pass  # Expected - we break the loop

    mock_redis.rpush.assert_called_once_with(
        "planner_tasks",
        json.dumps({"task_id": "task-123"})
    )
    assert mock_record.is_published is True
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_outbox_handles_redis_failure_gracefully():
    """Test that Redis failure for one record doesn't stop others from being published."""
    from models.database import Outbox
    import uuid

    mock_record1 = MagicMock(spec=Outbox)
    mock_record1.id = uuid.uuid4()
    mock_record1.redis_channel = "planner_tasks"
    mock_record1.message_json = {"task_id": "task-1"}
    mock_record1.correlation_id = uuid.uuid4()
    mock_record1.is_published = False

    mock_record2 = MagicMock(spec=Outbox)
    mock_record2.id = uuid.uuid4()
    mock_record2.redis_channel = "planner_tasks"
    mock_record2.message_json = {"task_id": "task-2"}
    mock_record2.correlation_id = uuid.uuid4()
    mock_record2.is_published = False

    mock_redis = AsyncMock()
    # First call fails, second succeeds
    mock_redis.rpush = AsyncMock(side_effect=[Exception("Redis error"), None])

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_record1, mock_record2]
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    with patch("core.outbox.AsyncSessionLocal") as mock_session, \
         patch("core.outbox.get_redis", new_callable=AsyncMock, return_value=mock_redis), \
         patch("asyncio.sleep", side_effect=StopAsyncIteration):

        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        try:
            await publish_outbox_records()
        except StopAsyncIteration:
            pass

    # First record should NOT be marked published (failed)
    assert mock_record1.is_published is False
    # Second record SHOULD be marked published (succeeded)
    assert mock_record2.is_published is True
