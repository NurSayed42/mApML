from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Task, User, get_db
from core.sse import stream_sse_events
from core.config import settings
from core.uuid_utils import parse_uuid

router = APIRouter(prefix="/stream", tags=["stream"])

ALGORITHM = "HS256"


async def verify_token_query(token: str = Query(...)) -> str:
    """Verify JWT passed as query param (for EventSource API compatibility)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise JWTError("Wrong token type")
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/{task_id}")
async def stream_task_events(
    task_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE stream for real-time task progress updates.
    JWT is passed as query parameter since EventSource doesn't support custom headers.
    """
    user_id = await verify_token_query(token)

    # Verify task ownership
    result = await db.execute(
        select(Task)
        .where(Task.id == parse_uuid(task_id))
        .where(Task.user_id == parse_uuid(user_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return StreamingResponse(
        stream_sse_events(user_id=user_id, task_id=task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
