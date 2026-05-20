import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from core.token_tracker import log_token_usage, flush_token_buffer, check_and_increment_gemini_rpm


@pytest.mark.asyncio
async def test_log_token_usage_adds_to_buffer():
    """Test that token usage is added to Redis buffer."""
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.llen = AsyncMock(return_value=3)  # Under flush threshold

    with patch("core.token_tracker.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        await log_token_usage(
            task_id="task-1",
            dag_node_id="node-1",
            user_id="user-1",
            correlation_id="corr-1",
            agent_name="research",
            model_name="gemini-1.5-flash",
            prompt_tokens=100,
            completion_tokens=200,
        )

    mock_redis.rpush.assert_called_once()
    call_args = json.loads(mock_redis.rpush.call_args[0][1])
    assert call_args["total_tokens"] == 300
    assert call_args["agent_name"] == "research"


@pytest.mark.asyncio
async def test_flush_token_buffer_writes_to_db():
    """Test buffer flush writes records to PostgreSQL."""
    record = {
        "task_id": "task-1",
        "dag_node_id": "node-1",
        "user_id": "user-1",
        "correlation_id": "corr-1",
        "agent_name": "research",
        "model_name": "gemini-1.5-flash",
        "prompt_tokens": 100,
        "completion_tokens": 200,
        "total_tokens": 300,
        "timestamp": 1000000.0,
    }

    mock_redis = AsyncMock()
    mock_redis.lpop = AsyncMock(side_effect=[json.dumps(record), None])

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    with patch("core.token_tracker.get_redis", new_callable=AsyncMock, return_value=mock_redis), \
         patch("core.token_tracker.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await flush_token_buffer()

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_rpm_check_allows_under_limit():
    """Test Gemini RPM allows calls under buffer threshold."""
    mock_redis = AsyncMock()
    mock_redis.pipeline.return_value.__aenter__ = AsyncMock()
    mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[5, True])  # count=5, expire=True
    mock_redis.pipeline.return_value = pipe

    with patch("core.token_tracker.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        result = await check_and_increment_gemini_rpm()

    assert result is True  # 5 < 13 (buffer threshold)


@pytest.mark.asyncio
async def test_gemini_rpm_check_blocks_at_limit():
    """Test Gemini RPM blocks at buffer threshold."""
    mock_redis = AsyncMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[13, True])  # count=13, at buffer
    mock_redis.pipeline.return_value = pipe

    with patch("core.token_tracker.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        result = await check_and_increment_gemini_rpm()

    assert result is False  # 13 >= 13 (buffer threshold)
