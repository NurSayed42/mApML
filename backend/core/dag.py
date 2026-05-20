import uuid
from typing import List, Dict, Optional, Tuple
import structlog
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from models.database import DAGNode, TaskDependency, Task

logger = structlog.get_logger(__name__)


async def create_dag_atomically(
    db: AsyncSession,
    parent_task_id: str,
    subtasks: List[Dict],
) -> List[DAGNode]:
    """
    Creates all DAG nodes and dependencies in a single atomic transaction.
    subtasks: list of dicts with keys: agent_role, task_type, payload, dependencies (list of agent_roles)
    """
    # Create all nodes first
    role_to_node: Dict[str, DAGNode] = {}

    for subtask in subtasks:
        node = DAGNode(
            id=uuid.uuid4(),
            parent_task_id=parent_task_id,
            agent_role=subtask["agent_role"],
            task_type=subtask["task_type"],
            payload=subtask["payload"],
            status="QUEUED",
            retry_count=0,
        )
        db.add(node)
        role_to_node[subtask["agent_role"]] = node

    await db.flush()  # Get IDs without committing

    # Create dependency edges
    for subtask in subtasks:
        node = role_to_node[subtask["agent_role"]]
        for dep_role in subtask.get("dependencies", []):
            if dep_role in role_to_node:
                dep_node = role_to_node[dep_role]
                dependency = TaskDependency(
                    dag_node_id=node.id,
                    depends_on_dag_node_id=dep_node.id,
                )
                db.add(dependency)

    # Don't commit - caller controls transaction
    logger.info(
        "dag_created_atomically",
        parent_task_id=parent_task_id,
        node_count=len(subtasks),
    )
    return list(role_to_node.values())


async def get_root_nodes(db: AsyncSession, parent_task_id: str) -> List[DAGNode]:
    """Get nodes with no dependencies (root nodes ready to execute immediately)."""
    # Nodes that have no entries in task_dependencies as dag_node_id
    result = await db.execute(
        select(DAGNode)
        .where(DAGNode.parent_task_id == parent_task_id)
        .where(DAGNode.status == "QUEUED")
        .where(
            ~DAGNode.id.in_(
                select(TaskDependency.dag_node_id)
            )
        )
    )
    return result.scalars().all()


async def resolve_dependencies_serializable(
    db: AsyncSession,
    completed_node_id: str,
    parent_task_id: str,
) -> List[DAGNode]:
    """
    Run inside a SERIALIZABLE transaction to prevent race conditions.
    Returns newly unblocked nodes ready to execute.
    """
    # Use serializable isolation for this critical section
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    # Get all nodes in this DAG
    all_nodes_result = await db.execute(
        select(DAGNode).where(DAGNode.parent_task_id == parent_task_id)
    )
    all_nodes = {n.id: n for n in all_nodes_result.scalars().all()}
    node_ids = list(all_nodes.keys())

    # Get all dependencies
    all_deps_result = await db.execute(
        select(TaskDependency).where(
            TaskDependency.dag_node_id.in_(node_ids)
        )
    )
    all_deps = all_deps_result.scalars().all()

    # Build dependency map: node_id -> set of dependency node_ids
    dep_map: Dict[uuid.UUID, set] = {nid: set() for nid in all_nodes}
    for dep in all_deps:
        dep_map[dep.dag_node_id].add(dep.depends_on_dag_node_id)

    # Find nodes that are now unblocked
    completed_statuses = {"COMPLETED", "FALLBACK"}
    unblocked = []

    for node_id, node in all_nodes.items():
        if node.status != "QUEUED":
            continue
        deps = dep_map.get(node_id, set())
        if all(
            all_nodes[dep_id].status in completed_statuses
            for dep_id in deps
            if dep_id in all_nodes
        ):
            unblocked.append(node)

    logger.info(
        "dependency_resolution",
        parent_task_id=parent_task_id,
        completed_node=completed_node_id,
        newly_unblocked=len(unblocked),
    )
    return unblocked


async def are_all_nodes_terminal(db: AsyncSession, parent_task_id: str) -> Tuple[bool, List[DAGNode]]:
    """Check if all DAG nodes have reached a terminal state."""
    result = await db.execute(
        select(DAGNode).where(DAGNode.parent_task_id == parent_task_id)
    )
    nodes = result.scalars().all()
    terminal_statuses = {"COMPLETED", "FAILED", "DLQ", "FALLBACK"}
    all_terminal = all(n.status in terminal_statuses for n in nodes)
    return all_terminal, nodes


async def get_dag_for_task(db: AsyncSession, parent_task_id: str) -> Tuple[List[DAGNode], List[TaskDependency]]:
    """Get all nodes and dependencies for a task DAG."""
    nodes_result = await db.execute(
        select(DAGNode).where(DAGNode.parent_task_id == parent_task_id)
    )
    nodes = nodes_result.scalars().all()

    node_ids = [n.id for n in nodes]
    if not node_ids:
        return nodes, []
    deps_result = await db.execute(
        select(TaskDependency).where(TaskDependency.dag_node_id.in_(node_ids))
    )
    deps = deps_result.scalars().all()

    return nodes, deps
