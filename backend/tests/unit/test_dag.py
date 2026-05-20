import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call
from core.dag import create_dag_atomically, get_root_nodes, are_all_nodes_terminal


@pytest.mark.asyncio
async def test_create_dag_atomically_creates_nodes():
    """Test that all nodes are created correctly."""
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    subtasks = [
        {"agent_role": "research", "task_type": "market_research", "payload": {}, "dependencies": []},
        {"agent_role": "content", "task_type": "content_gen", "payload": {}, "dependencies": ["research"]},
        {"agent_role": "aggregator", "task_type": "aggregate", "payload": {}, "dependencies": ["research", "content"]},
    ]

    parent_task_id = str(uuid.uuid4())
    nodes = await create_dag_atomically(mock_db, parent_task_id, subtasks)

    # Should have called db.add for 3 nodes + 3 dependencies
    assert mock_db.add.call_count == 3 + 3  # nodes + dependencies
    assert len(nodes) == 3


@pytest.mark.asyncio
async def test_create_dag_atomically_no_dependencies():
    """Test DAG creation with no dependencies (all root nodes)."""
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    subtasks = [
        {"agent_role": "research", "task_type": "research", "payload": {}, "dependencies": []},
        {"agent_role": "analytics", "task_type": "analytics", "payload": {}, "dependencies": []},
    ]

    nodes = await create_dag_atomically(mock_db, "task-id", subtasks)

    # 2 nodes + 0 dependencies
    assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_are_all_nodes_terminal_all_completed():
    """Test terminal check when all nodes completed."""
    from models.database import DAGNode

    mock_db = AsyncMock()
    mock_nodes = [
        MagicMock(status="COMPLETED"),
        MagicMock(status="COMPLETED"),
        MagicMock(status="FALLBACK"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_nodes
    mock_db.execute = AsyncMock(return_value=mock_result)

    all_done, nodes = await are_all_nodes_terminal(mock_db, "task-id")
    assert all_done is True


@pytest.mark.asyncio
async def test_are_all_nodes_terminal_some_in_progress():
    """Test terminal check when some nodes still running."""
    mock_db = AsyncMock()
    mock_nodes = [
        MagicMock(status="COMPLETED"),
        MagicMock(status="IN_PROGRESS"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_nodes
    mock_db.execute = AsyncMock(return_value=mock_result)

    all_done, nodes = await are_all_nodes_terminal(mock_db, "task-id")
    assert all_done is False


@pytest.mark.asyncio
async def test_are_all_nodes_terminal_with_dlq():
    """Test that DLQ counts as terminal."""
    mock_db = AsyncMock()
    mock_nodes = [
        MagicMock(status="COMPLETED"),
        MagicMock(status="DLQ"),
        MagicMock(status="FAILED"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_nodes
    mock_db.execute = AsyncMock(return_value=mock_result)

    all_done, nodes = await are_all_nodes_terminal(mock_db, "task-id")
    assert all_done is True


@pytest.mark.asyncio
async def test_are_all_nodes_terminal_empty():
    """Test with no nodes (edge case)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    all_done, nodes = await are_all_nodes_terminal(mock_db, "task-id")
    assert all_done is True
    assert nodes == []
