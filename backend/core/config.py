from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


def normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy async engine uses the asyncpg driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    # Required fields (এই নামগুলো .env এ থাকতে হবে)
    gemini_api_key: str
    groq_api_key: str = ""
    mistral_api_key: str = ""
    database_url: str
    redis_url: str
    jwt_secret_key: str
    
    # Optional fields with defaults
    tavily_api_key: str = ""
    resend_api_key: str = ""
    chroma_url: str = "http://localhost:8000"
    environment: str = "development"
    allowed_origin: str = "http://localhost:3000"
    emailjs_service_id: str = ""
    emailjs_template_id: str = ""
    emailjs_public_key: str = ""

    # App settings
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    max_scheduled_tasks_per_user: int = 5
    task_retention_days: int = 90
    conversation_retention_days: int = 180
    token_usage_retention_months: int = 12
    max_file_size_mb: int = 10
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 50
    short_term_memory_limit: int = 10
    session_memory_ttl_seconds: int = 7200
    research_cache_similarity_threshold: float = 0.85
    research_cache_age_hours: int = 24
    long_term_memory_similarity_threshold: float = 0.75
    tavily_monthly_limit: int = 900
    resend_daily_limit: int = 100
    gemini_rpm_limit: int = 15
    gemini_rpm_buffer: int = 13
    token_buffer_flush_count: int = 10
    token_buffer_flush_seconds: int = 30
    retry_backoff_first: int = 30
    retry_backoff_second: int = 90
    worker_lock_ttl_seconds: int = 90
    dlq_redis_ttl_hours: int = 72
    idempotency_window_minutes: int = 5
    redis_connect_timeout_seconds: int = 10
    redis_socket_timeout_seconds: int = 10
    worker_queue_poll_timeout_seconds: int = 5
    worker_backup_drain_max_messages: int = 10_000
    llm_request_timeout_seconds: int = 90

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        return normalize_database_url(v)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",  # handles UTF-8 BOM on Windows .env files
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()