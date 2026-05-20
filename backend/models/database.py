from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column, String, Boolean, Integer, Text, DateTime, ForeignKey, JSON,
    Enum as SAEnum, UniqueConstraint, CheckConstraint, Index, func, text
)
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from core.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.environment == "development",
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="standard", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("role IN ('standard', 'admin')", name="users_role_check"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    raw_input = Column(Text, nullable=False)
    status = Column(String(20), default="RECEIVED", nullable=False)
    final_output = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    output_nulled_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('RECEIVED','PLANNED','IN_PROGRESS','COMPLETED','FAILED','FALLBACK')",
            name="tasks_status_check"
        ),
        Index("ix_tasks_user_id", "user_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_correlation_id", "correlation_id"),
    )


class DAGNode(Base):
    __tablename__ = "dag_nodes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    agent_role = Column(String(50), nullable=False)
    task_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    output_chroma_doc_id = Column(String(255), nullable=True)
    status = Column(String(20), default="QUEUED", nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    retry_after = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','IN_PROGRESS','COMPLETED','FAILED','DLQ','FALLBACK')",
            name="dag_nodes_status_check"
        ),
        Index("ix_dag_nodes_parent_task_id", "parent_task_id"),
        Index("ix_dag_nodes_status", "status"),
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    dag_node_id = Column(UUID(as_uuid=True), ForeignKey("dag_nodes.id"), primary_key=True)
    depends_on_dag_node_id = Column(UUID(as_uuid=True), ForeignKey("dag_nodes.id"), primary_key=True)


class Outbox(Base):
    __tablename__ = "outbox"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    redis_channel = Column(String(100), nullable=False)
    message_json = Column(JSON, nullable=False)
    is_published = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_outbox_is_published", "is_published", postgresql_where=text("is_published = false")),
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dag_node_id = Column(UUID(as_uuid=True), ForeignKey("dag_nodes.id"), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    agent_name = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    detail = Column(Text, nullable=True)
    status = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class TokenUsage(Base):
    __tablename__ = "token_usage"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    dag_node_id = Column(UUID(as_uuid=True), ForeignKey("dag_nodes.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    agent_name = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class AgentError(Base):
    __tablename__ = "agent_errors"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dag_node_id = Column(UUID(as_uuid=True), nullable=True)
    task_id = Column(UUID(as_uuid=True), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    agent_name = Column(String(50), nullable=False)
    error_type = Column(String(100), nullable=False)
    error_message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)
    is_in_dlq = Column(Boolean, default=False, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    embedding_doc_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    task_description = Column(Text, nullable=False)
    cron_expression = Column(String(100), nullable=True)
    run_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmailRecord(Base):
    __tablename__ = "email_records"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dag_node_id = Column(UUID(as_uuid=True), ForeignKey("dag_nodes.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    delivery_status = Column(String(20), nullable=False)
    sent_via = Column(String(50), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "delivery_status IN ('SENT','UNSENT','FAILED')",
            name="email_records_status_check"
        ),
    )


class DataRetentionLog(Base):
    __tablename__ = "data_retention_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at = Column(DateTime(timezone=True), server_default=func.now())
    tasks_output_nulled = Column(Integer, nullable=False, default=0)
    chroma_docs_deleted = Column(Integer, nullable=False, default=0)
    conversation_embeddings_deleted = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
