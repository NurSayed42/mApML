import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_retry_count_incremented_on_failure():
    """Test that retry_count is incremented on task failure."""
    from workers.base_worker import BaseWorker

    class TestWorker(BaseWorker):
        WORKER_NAME = "test"
        QUEUE_CHANNEL = "test_tasks"
        BACKUP_CHANNEL = "test_tasks_backup"

        async def process(self, message, log):
            raise ValueError("Simulated failure")

    worker = TestWorker()
    message = {
        "task_id": "task-1",
        "dag_node_id": "node-1",
        "user_id": "user-1",
        "correlation_id": "corr-1",
        "agent_role": "test",
        "task_type": "test",
        "payload": {},
        "retry_count": 0,
    }

    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.delete = AsyncMock()
    worker.redis = mock_redis

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    with patch("workers.base_worker.AsyncSessionLocal") as mock_session, \
         patch("workers.base_worker.push_sse_event", new_callable=AsyncMock):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._handle_failure(message, ValueError("Test error"), MagicMock())

    # Should have been re-queued with retry_count=1
    requeue_call = mock_redis.rpush.call_args_list[0]
    requeued_msg = json.loads(requeue_call[0][1])
    assert requeued_msg["retry_count"] == 1
    assert requeued_msg["retry_after"] is not None


@pytest.mark.asyncio
async def test_dlq_escalation_after_two_retries():
    """Test task moves to DLQ after 2 retries."""
    from workers.base_worker import BaseWorker

    class TestWorker(BaseWorker):
        WORKER_NAME = "test"
        QUEUE_CHANNEL = "test_tasks"
        BACKUP_CHANNEL = "test_tasks_backup"

        async def process(self, message, log):
            raise ValueError("Persistent failure")

    worker = TestWorker()
    message = {
        "task_id": "task-1",
        "dag_node_id": "node-1",
        "user_id": "user-1",
        "correlation_id": "corr-1",
        "agent_role": "test",
        "task_type": "test",
        "payload": {},
        "retry_count": 2,  # Already retried twice
    }

    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.delete = AsyncMock()
    worker.redis = mock_redis

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock()

    with patch("workers.base_worker.AsyncSessionLocal") as mock_session, \
         patch("workers.base_worker.push_sse_event", new_callable=AsyncMock):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._handle_failure(message, ValueError("Final failure"), MagicMock())

    # Should have pushed to DLQ
    dlq_push = next(
        (call for call in mock_redis.rpush.call_args_list
         if call[0][0] == "dead_letter_queue"),
        None
    )
    assert dlq_push is not None, "Task should have been pushed to DLQ"


@pytest.mark.asyncio
async def test_backoff_timing_first_retry():
    """Test first retry has 30s backoff."""
    from workers.base_worker import BaseWorker

    class TestWorker(BaseWorker):
        WORKER_NAME = "test"
        QUEUE_CHANNEL = "test_tasks"
        BACKUP_CHANNEL = "test_tasks_backup"

        async def process(self, message, log):
            raise ValueError("Failure")

    worker = TestWorker()
    message = {
        "task_id": "task-1",
        "dag_node_id": "node-1",
        "user_id": "user-1",
        "correlation_id": "corr-1",
        "agent_role": "test",
        "retry_count": 0,  # First failure
        "payload": {},
    }

    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    worker.redis = mock_redis

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock()

    before = datetime.now(timezone.utc)

    with patch("workers.base_worker.AsyncSessionLocal") as mock_session, \
         patch("workers.base_worker.push_sse_event", new_callable=AsyncMock):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._handle_failure(message, ValueError("Error"), MagicMock())

    # Check retry_after is ~30s in the future
    requeue_call = mock_redis.rpush.call_args_list[0]
    requeued_msg = json.loads(requeue_call[0][1])
    retry_after = datetime.fromisoformat(requeued_msg["retry_after"])

    diff = (retry_after - before).total_seconds()
    assert 25 <= diff <= 35, f"Backoff should be ~30s, got {diff}s"


def test_idempotency_key_generation():
    """Test that same user+instruction always produces same key."""
    import hashlib

    def generate_key(user_id, instruction):
        content = f"{user_id}:{instruction}"
        return hashlib.sha256(content.encode()).hexdigest()

    key1 = generate_key("user-123", "Create marketing campaign")
    key2 = generate_key("user-123", "Create marketing campaign")
    key3 = generate_key("user-456", "Create marketing campaign")
    key4 = generate_key("user-123", "Different instruction")

    assert key1 == key2, "Same inputs should produce same key"
    assert key1 != key3, "Different users should produce different keys"
    assert key1 != key4, "Different instructions should produce different keys"
