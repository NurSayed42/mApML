import asyncio
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import settings
from models.database import init_db
from core.outbox import publish_outbox_records
from core.token_tracker import periodic_flush
from core.retention import run_retention_job

from api.v1.auth import router as auth_router
from api.v1.tasks import router as tasks_router
from api.v1.documents import router as documents_router
from api.v1.stream import router as stream_router
from api.v1.admin import router as admin_router
from api.v1.health import router as health_router

logger = structlog.get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)

scheduler = AsyncIOScheduler()
background_tasks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("startup_begin", environment=settings.environment)

    # Initialize database tables
    await init_db()

    # Start background tasks
    outbox_task = asyncio.create_task(publish_outbox_records())
    flush_task = asyncio.create_task(periodic_flush())
    background_tasks.extend([outbox_task, flush_task])

    # Schedule daily retention job at 2 AM UTC
    scheduler.add_job(
        run_retention_job,
        "cron",
        hour=2,
        minute=0,
        timezone="UTC",
        id="retention_job",
        replace_existing=True,
    )

    # Schedule APScheduler-managed user tasks
    scheduler.add_job(
        _run_scheduled_user_tasks,
        "interval",
        minutes=1,
        id="user_scheduled_tasks",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("startup_complete")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    for task in background_tasks:
        task.cancel()
    logger.info("shutdown_complete")


async def _run_scheduled_user_tasks():
    """Check for scheduled user tasks that are due and submit them."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from models.database import ScheduledTask, Task, AsyncSessionLocal
    from core.outbox import create_outbox_record
    from core.scheduling import cron_task_is_due
    import uuid

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledTask).where(ScheduledTask.is_active == True)
        )
        scheduled_tasks = result.scalars().all()

        for st in scheduled_tasks:
            is_due = False
            if st.cron_expression:
                is_due = cron_task_is_due(st.cron_expression, now, st.last_run_at)
            elif st.run_at and st.run_at <= now and st.last_run_at is None:
                is_due = True

            if not is_due:
                continue

            task_id = uuid.uuid4()
            correlation_id = uuid.uuid4()

            task = Task(
                id=task_id,
                user_id=st.user_id,
                idempotency_key=f"scheduled_{st.id}_{now.isoformat()}",
                correlation_id=correlation_id,
                title=st.task_description[:100],
                raw_input=st.task_description,
                status="RECEIVED",
            )
            db.add(task)
            await db.flush()

            await create_outbox_record(
                db=db,
                task_id=str(task_id),
                correlation_id=str(correlation_id),
                redis_channel="planner_tasks",
                message={
                    "task_id": str(task_id),
                    "parent_task_id": str(task_id),
                    "dag_node_id": None,
                    "user_id": str(st.user_id),
                    "correlation_id": str(correlation_id),
                    "agent_role": "planner",
                    "task_type": "plan_task",
                    "payload": {
                        "instruction": st.task_description,
                        "user_id": str(st.user_id),
                        "session_id": str(uuid.uuid4()),
                    },
                    "retry_count": 0,
                },
            )

            st.last_run_at = now
            if not st.cron_expression:
                st.is_active = False

        await db.commit()


app = FastAPI(
    title="Multi-Agent AI Business Automation Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Correlation ID middleware
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    import uuid
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# API Routes
PREFIX = "/api/v1"
app.include_router(auth_router, prefix=PREFIX)
app.include_router(tasks_router, prefix=PREFIX)
app.include_router(documents_router, prefix=PREFIX)
app.include_router(stream_router, prefix=PREFIX)
app.include_router(admin_router, prefix=PREFIX)
app.include_router(health_router, prefix=PREFIX)


@app.get("/")
async def root():
    return {
        "name": "Multi-Agent AI Business Automation Platform",
        "version": "1.0.0",
        "docs": "/docs",
    }
