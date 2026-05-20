import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from models.database import Task, DAGNode, TaskDependency, ScheduledTask, get_db
from models.schemas import TaskCreate, TaskOut, TaskListOut, ScheduledTaskCreate, ScheduledTaskOut, DAGOut
from api.v1.auth import get_current_user
from models.database import User
from core.outbox import create_outbox_record
from core.injection_filter import validate_and_sanitize
from core.config import settings
from core.uuid_utils import parse_uuid

router = APIRouter(prefix="/tasks", tags=["tasks"])


def generate_idempotency_key(user_id: str, instruction: str) -> str:
    content = f"{user_id}:{instruction}"
    return hashlib.sha256(content.encode()).hexdigest()


@router.post("", status_code=202, response_model=TaskOut)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sanitized, is_safe, matched = validate_and_sanitize(
        body.instruction,
        correlation_id="",
        user_id=str(user.id),
    )
    if not is_safe:
        raise HTTPException(status_code=400, detail="Input rejected: contains disallowed patterns")

    idem_key = body.idempotency_key or generate_idempotency_key(str(user.id), sanitized)

    # Check idempotency — no time window, just check if key exists at all
    # (simpler and prevents the race condition)
    result = await db.execute(
        select(Task).where(Task.idempotency_key == idem_key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    correlation_id = uuid.uuid4()
    task = Task(
        user_id=user.id,
        idempotency_key=idem_key,
        correlation_id=correlation_id,
        title=sanitized[:100],
        raw_input=sanitized,
        status="RECEIVED",
        scheduled_at=body.scheduled_at,
    )
    db.add(task)

    try:
        await db.flush()
    except IntegrityError:
        # Race condition: another request inserted the same key simultaneously
        await db.rollback()
        result = await db.execute(
            select(Task).where(Task.idempotency_key == idem_key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        raise HTTPException(status_code=500, detail="Task creation conflict, please retry")

    planner_message = {
        "task_id": str(task.id),
        "parent_task_id": str(task.id),
        "dag_node_id": None,
        "user_id": str(user.id),
        "correlation_id": str(correlation_id),
        "agent_role": "planner",
        "task_type": "plan_task",
        "payload": {
            "instruction": sanitized,
            "user_id": str(user.id),
            "session_id": str(body.session_id) if body.session_id else str(uuid.uuid4()),
        },
        "retry_count": 0,
    }

    await create_outbox_record(
        db=db,
        task_id=str(task.id),
        correlation_id=str(correlation_id),
        redis_channel="planner_tasks",
        message=planner_message,
    )

    await db.commit()
    await db.refresh(task)
    return task


@router.get("", response_model=TaskListOut)
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Task).where(Task.user_id == user.id)
    if status:
        query = query.where(Task.status == status.upper())
    query = query.order_by(Task.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    count_query = select(func.count()).select_from(Task).where(Task.user_id == user.id)
    if status:
        count_query = count_query.where(Task.status == status.upper())
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return TaskListOut(tasks=tasks, total=total)


@router.get("/scheduled", response_model=list[ScheduledTaskOut])
async def list_scheduled_tasks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ScheduledTask)
        .where(ScheduledTask.user_id == user.id)
        .where(ScheduledTask.is_active == True)
    )
    return result.scalars().all()


@router.post("/scheduled", response_model=ScheduledTaskOut)
async def create_scheduled_task(
    body: ScheduledTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count_result = await db.execute(
        select(func.count())
        .select_from(ScheduledTask)
        .where(ScheduledTask.user_id == user.id)
        .where(ScheduledTask.is_active == True)
    )
    if count_result.scalar() >= settings.max_scheduled_tasks_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {settings.max_scheduled_tasks_per_user} scheduled tasks allowed"
        )

    if not body.cron_expression and not body.run_at:
        raise HTTPException(status_code=400, detail="Either cron_expression or run_at is required")

    task = ScheduledTask(
        user_id=user.id,
        task_description=body.task_description,
        cron_expression=body.cron_expression,
        run_at=body.run_at,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/scheduled/{task_id}", status_code=204)
async def cancel_scheduled_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ScheduledTask)
        .where(ScheduledTask.id == parse_uuid(task_id))
        .where(ScheduledTask.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    task.is_active = False
    await db.commit()


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Task)
        .where(Task.id == parse_uuid(task_id))
        .where(Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/dag", response_model=DAGOut)
async def get_task_dag(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_uuid = parse_uuid(task_id)
    task_result = await db.execute(
        select(Task).where(Task.id == task_uuid).where(Task.user_id == user.id)
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    nodes_result = await db.execute(
        select(DAGNode).where(DAGNode.parent_task_id == task_uuid)
    )
    nodes = nodes_result.scalars().all()

    node_ids = [n.id for n in nodes]
    deps_result = await db.execute(
        select(TaskDependency).where(TaskDependency.dag_node_id.in_(node_ids))
    ) if node_ids else None
    deps = deps_result.scalars().all() if deps_result else []
    return DAGOut(
        nodes=nodes,
        dependencies=[
            {
                "from": str(d.depends_on_dag_node_id),
                "to": str(d.dag_node_id),
            }
            for d in deps
        ],
    )