from fastapi import APIRouter
from core.locks import get_redis
from models.database import engine
import time

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    start = time.time()
    status = {"status": "ok", "services": {}}

    # Check Redis
    try:
        redis = await get_redis()
        await redis.ping()
        status["services"]["redis"] = "ok"
    except Exception as e:
        status["services"]["redis"] = f"error: {str(e)}"
        status["status"] = "degraded"

    # Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        status["services"]["postgres"] = "ok"
    except Exception as e:
        status["services"]["postgres"] = f"error: {str(e)}"
        status["status"] = "degraded"

    status["latency_ms"] = round((time.time() - start) * 1000, 2)
    return status
