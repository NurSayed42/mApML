from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime
import re


# ─── Auth Schemas ──────────────────────────────────────────────
class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def password_must_have_number(cls, v):
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


# ─── Task Schemas ───────────────────────────────────────────────
class TaskCreate(BaseModel):
    instruction: str = Field(..., min_length=5, max_length=5000)
    session_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class TaskOut(BaseModel):
    id: UUID
    title: str
    status: str
    correlation_id: UUID
    created_at: datetime
    completed_at: Optional[datetime]
    final_output: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


class TaskListOut(BaseModel):
    tasks: List[TaskOut]
    total: int


# ─── DAG Schemas ────────────────────────────────────────────────
class DAGNodeOut(BaseModel):
    id: UUID
    agent_role: str
    task_type: str
    status: str
    retry_count: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_ms: Optional[int]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class DAGOut(BaseModel):
    nodes: List[DAGNodeOut]
    dependencies: List[Dict[str, str]]


# ─── SSE Event Schemas ──────────────────────────────────────────
class SSEEvent(BaseModel):
    event_type: str
    event_schema_version: str = "v1"
    correlation_id: str
    task_id: str
    timestamp: str
    data: Dict[str, Any]


# ─── Admin Schemas ──────────────────────────────────────────────
class PlatformStats(BaseModel):
    total_tasks_today: int
    total_tokens_today: int
    agent_success_rates: Dict[str, float]
    dlq_count: int
    active_users_today: int


class DLQItem(BaseModel):
    task_id: Optional[str]
    dag_node_id: Optional[str]
    correlation_id: str
    agent_name: str
    error_type: str
    error_message: str
    created_at: str


class RequeueRequest(BaseModel):
    correlation_id: str


class UpdateUserRole(BaseModel):
    role: str = Field(..., pattern="^(standard|admin)$")


class DeactivateUser(BaseModel):
    is_active: bool


# ─── Document Schemas ───────────────────────────────────────────
class DocumentOut(BaseModel):
    id: UUID
    filename: str
    file_type: str
    chunk_count: int
    upload_timestamp: datetime

    class Config:
        from_attributes = True


class RAGQuery(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    document_id: Optional[UUID] = None


# ─── Scheduled Task Schemas ─────────────────────────────────────
class ScheduledTaskCreate(BaseModel):
    task_description: str = Field(..., min_length=5, max_length=2000)
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v):
        if v is not None:
            parts = v.strip().split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have 5 parts")
        return v


class ScheduledTaskOut(BaseModel):
    id: UUID
    task_description: str
    cron_expression: Optional[str]
    run_at: Optional[datetime]
    is_active: bool
    last_run_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Token Usage Schemas ────────────────────────────────────────
class TokenUsageOut(BaseModel):
    agent_name: str
    model_name: str
    total_tokens: int
    timestamp: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class TokenUsageSummary(BaseModel):
    total_tokens: int
    by_agent: Dict[str, int]
    period_days: int
