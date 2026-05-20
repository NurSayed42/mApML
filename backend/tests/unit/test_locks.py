import pytest
from unittest.mock import AsyncMock, MagicMock
from core.locks import DistributedLock, acquire_lock, release_lock


@pytest.mark.asyncio
async def test_lock_acquire_success():
    """Test successful lock acquisition."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    lock = DistributedLock(mock_redis, "task-123", ttl=90)
    acquired = await lock.acquire()

    assert acquired is True
    assert lock._acquired is True
    mock_redis.set.assert_called_once_with("lock:task-123", "1", nx=True, ex=90)


@pytest.mark.asyncio
async def test_lock_acquire_failure_already_locked():
    """Test lock acquisition when already held by another worker."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # Redis returns None when NX fails

    lock = DistributedLock(mock_redis, "task-123", ttl=90)
    acquired = await lock.acquire()

    assert acquired is False
    assert lock._acquired is False


@pytest.mark.asyncio
async def test_lock_release():
    """Test lock release deletes the key."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    lock = DistributedLock(mock_redis, "task-123", ttl=90)
    await lock.acquire()
    await lock.release()

    mock_redis.delete.assert_called_once_with("lock:task-123")
    assert lock._acquired is False


@pytest.mark.asyncio
async def test_lock_release_without_acquire():
    """Test that release does nothing if lock was not acquired."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    lock = DistributedLock(mock_redis, "task-123", ttl=90)
    await lock.release()  # Should not raise

    mock_redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_lock_context_manager():
    """Test lock as async context manager."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    lock = DistributedLock(mock_redis, "task-ctx")
    async with lock:
        assert lock._acquired is True
        mock_redis.set.assert_called_once()

    mock_redis.delete.assert_called_once()
    assert lock._acquired is False


@pytest.mark.asyncio
async def test_acquire_lock_helper():
    """Test acquire_lock helper function."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    result = await acquire_lock(mock_redis, "task-456")
    assert result is True


@pytest.mark.asyncio
async def test_release_lock_helper():
    """Test release_lock helper function."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    await release_lock(mock_redis, "task-456")
    mock_redis.delete.assert_called_once_with("lock:task-456")
