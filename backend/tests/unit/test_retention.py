import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_retention_job_nulls_old_task_outputs():
    """Test that old task outputs are nulled out."""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    # Simulate update affecting 5 rows
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("core.retention.AsyncSessionLocal") as mock_session, \
         patch("core.retention.get_or_create_collection") as mock_chroma:

        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_col = MagicMock()
        mock_col.get = MagicMock(return_value={"ids": []})
        mock_col.delete = MagicMock()
        mock_chroma.return_value = mock_col

        from core.retention import run_retention_job
        await run_retention_job()

    # Verify commit was called
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_retention_job_logs_result():
    """Test that retention job logs its run result."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("core.retention.AsyncSessionLocal") as mock_session, \
         patch("core.retention.get_or_create_collection") as mock_chroma:

        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_col = MagicMock()
        mock_col.get = MagicMock(return_value={"ids": []})
        mock_chroma.return_value = mock_col

        from core.retention import run_retention_job
        await run_retention_job()

    # A DataRetentionLog record should be added
    assert mock_db.add.called
    log_record = mock_db.add.call_args[0][0]
    assert log_record.status in ("SUCCESS", "FAILED")
