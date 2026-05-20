import json
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    Task, DAGNode, AgentError, TokenUsage, User, DataRetentionLog, get_db
)
from models.schemas import PlatformStats, DLQItem, RequeueRequest, UpdateUserRole, DeactivateUser
from api.v1.auth import require_admin, get_current_user
from core.locks import get_redis
from core.retention import run_retention_job

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=PlatformStats)
async def get_platform_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Tasks today
    tasks_today = await db.execute(
        select(func.count()).select_from(Task).where(Task.created_at >= today_start)
    )
    total_tasks_today = tasks_today.scalar()

    # Tokens today
    tokens_today = await db.execute(
        select(func.sum(TokenUsage.total_tokens)).where(TokenUsage.timestamp >= today_start)
    )
    total_tokens_today = tokens_today.scalar() or 0

    # Active users today
    active_users = await db.execute(
        select(func.count(distinct(Task.user_id))).where(Task.created_at >= today_start)
    )
    active_users_today = active_users.scalar()

    # Agent success rates (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    nodes_result = await db.execute(
        select(DAGNode.agent_role, DAGNode.status)
        .where(DAGNode.started_at >= seven_days_ago)
    )
    nodes = nodes_result.fetchall()

    role_totals: dict = {}
    role_success: dict = {}
    for role, status in nodes:
        role_totals[role] = role_totals.get(role, 0) + 1
        if status in ("COMPLETED", "FALLBACK"):
            role_success[role] = role_success.get(role, 0) + 1

    success_rates = {
        role: round(role_success.get(role, 0) / total, 2)
        for role, total in role_totals.items()
        if total > 0
    }

    # DLQ count
    redis = await get_redis()
    dlq_count = await redis.llen("dead_letter_queue")

    return PlatformStats(
        total_tasks_today=total_tasks_today,
        total_tokens_today=total_tokens_today,
        agent_success_rates=success_rates,
        dlq_count=dlq_count,
        active_users_today=active_users_today,
    )


@router.get("/dlq", response_model=list[DLQItem])
async def get_dlq_items(
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
):
    """Get Dead Letter Queue items."""
    redis = await get_redis()
    raw_items = await redis.lrange("dead_letter_queue", 0, limit - 1)

    items = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
            items.append(DLQItem(
                task_id=item.get("task_id"),
                dag_node_id=item.get("dag_node_id"),
                correlation_id=item.get("correlation_id", ""),
                agent_name=item.get("worker", item.get("agent_role", "unknown")),
                error_type=item.get("error_type") or "WorkerError",
                error_message=str(item.get("final_error") or item.get("error_message", "")),
                created_at=item.get("created_at", ""),
            ))
        except Exception:
            pass

    return items


@router.post("/dlq/requeue")
async def requeue_dlq_item(
    body: RequeueRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-queue a DLQ item by correlation_id."""
    redis = await get_redis()
    raw_items = await redis.lrange("dead_letter_queue", 0, -1)

    for raw in raw_items:
        try:
            item = json.loads(raw)
            if item.get("correlation_id") == body.correlation_id:
                item["retry_count"] = 0
                item.pop("retry_after", None)
                item.pop("final_error", None)

                channel = f"{item.get('agent_role', 'planner')}_tasks"
                await redis.rpush(channel, json.dumps(item))
                await redis.lrem("dead_letter_queue", 1, raw)

                dag_node_id = item.get("dag_node_id")
                if dag_node_id:
                    await db.execute(
                        update(DAGNode)
                        .where(DAGNode.id == uuid.UUID(str(dag_node_id)))
                        .values(
                            status="QUEUED",
                            retry_count=0,
                            retry_after=None,
                            error_message=None,
                        )
                    )
                    await db.execute(
                        update(AgentError)
                        .where(AgentError.correlation_id == uuid.UUID(body.correlation_id))
                        .values(is_resolved=True, is_in_dlq=False)
                    )
                    await db.commit()

                return {"message": f"Item re-queued to {channel}"}
        except Exception:
            pass

    raise HTTPException(status_code=404, detail="DLQ item not found")


@router.get("/users", response_model=list)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: UpdateUserRole,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user_uuid = uuid.UUID(user_id)
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(update(User).where(User.id == user_uuid).values(role=body.role))
    await db.commit()
    return {"message": f"Role updated to {body.role}"}


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    body: DeactivateUser,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user_uuid = uuid.UUID(user_id)
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(update(User).where(User.id == user_uuid).values(is_active=body.is_active))
    await db.commit()
    return {"message": f"User {'activated' if body.is_active else 'deactivated'}"}


@router.post("/retention/trigger")
async def trigger_retention(admin: User = Depends(require_admin)):
    """Manually trigger data retention job."""
    import asyncio
    asyncio.create_task(run_retention_job())
    return {"message": "Retention job triggered"}


@router.get("/token-usage")
async def get_token_usage(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            TokenUsage.agent_name,
            func.sum(TokenUsage.total_tokens).label("total"),
            func.count().label("calls"),
        )
        .where(TokenUsage.timestamp >= cutoff)
        .group_by(TokenUsage.agent_name)
    )
    rows = result.fetchall()
    return {
        "period_days": days,
        "by_agent": [
            {"agent": r.agent_name, "total_tokens": r.total, "api_calls": r.calls}
            for r in rows
        ],
        "grand_total": sum(r.total for r in rows),
    }


@router.get("/errors")
async def get_agent_errors(
    unresolved_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = select(AgentError).order_by(AgentError.created_at.desc()).limit(limit)
    if unresolved_only:
        query = query.where(AgentError.is_resolved == False)

    result = await db.execute(query)
    errors = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "agent_name": e.agent_name,
            "error_type": e.error_type,
            "error_message": e.error_message,
            "correlation_id": str(e.correlation_id),
            "is_in_dlq": e.is_in_dlq,
            "created_at": e.created_at.isoformat(),
        }
        for e in errors
    ]
