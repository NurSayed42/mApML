import asyncio
from datetime import datetime, timezone, timedelta
import structlog
from sqlalchemy import update, delete, select, func
from models.database import Task, Conversation, TokenUsage, DataRetentionLog, AsyncSessionLocal
from core.config import settings

logger = structlog.get_logger(__name__)


async def run_retention_job():
    """
    Daily data retention cleanup job.
    - Tasks older than 90 days: null final_output
    - ChromaDB task embeddings older than 90 days: delete
    - Conversation embeddings older than 180 days: delete
    - Token usage older than 12 months: delete
    """
    logger.info("data_retention_job_started")
    tasks_nulled = 0
    chroma_deleted = 0
    conv_deleted = 0
    status = "SUCCESS"
    error_msg = None

    now = datetime.now(timezone.utc)
    task_cutoff = now - timedelta(days=settings.task_retention_days)
    conv_cutoff = now - timedelta(days=settings.conversation_retention_days)
    token_cutoff = now - timedelta(days=settings.token_usage_retention_months * 30)

    try:
        async with AsyncSessionLocal() as db:
            # 1. Null task outputs older than 90 days
            result = await db.execute(
                update(Task)
                .where(Task.created_at < task_cutoff)
                .where(Task.final_output != None)
                .values(final_output=None, output_nulled_at=now)
            )
            tasks_nulled = result.rowcount

            # 2. Delete old token usage
            await db.execute(
                delete(TokenUsage).where(TokenUsage.timestamp < token_cutoff)
            )

            # 3. Delete old conversations
            old_convs_result = await db.execute(
                select(Conversation.embedding_doc_id)
                .where(Conversation.created_at < conv_cutoff)
                .where(Conversation.embedding_doc_id != None)
            )
            old_conv_doc_ids = [r[0] for r in old_convs_result.fetchall()]

            await db.execute(
                delete(Conversation).where(Conversation.created_at < conv_cutoff)
            )
            conv_deleted = len(old_conv_doc_ids)

            await db.commit()

        # 4. ChromaDB cleanup
        try:
            from core.rag import get_or_create_collection
            import time

            task_cutoff_ts = task_cutoff.timestamp()
            conv_cutoff_ts = conv_cutoff.timestamp()

            # Delete old task outputs from ChromaDB
            task_col = get_or_create_collection("task_outputs")
            task_results = task_col.get(
                where={"created_at": {"$lt": task_cutoff_ts}},
                include=["metadatas"],
            )
            if task_results["ids"]:
                task_col.delete(ids=task_results["ids"])
                chroma_deleted += len(task_results["ids"])

            # Delete old conversation embeddings (if stored in Chroma)
            if old_conv_doc_ids:
                conv_col = get_or_create_collection("conversations")
                conv_col.delete(ids=old_conv_doc_ids)

        except Exception as e:
            logger.error("chroma_retention_error", error=str(e))

    except Exception as e:
        status = "FAILED"
        error_msg = str(e)
        logger.error("data_retention_job_failed", error=str(e))

    # Log results
    try:
        async with AsyncSessionLocal() as db:
            log = DataRetentionLog(
                tasks_output_nulled=tasks_nulled,
                chroma_docs_deleted=chroma_deleted,
                conversation_embeddings_deleted=conv_deleted,
                status=status,
                error_message=error_msg,
            )
            db.add(log)
            await db.commit()
    except Exception as e:
        logger.error("retention_log_write_failed", error=str(e))

    logger.info(
        "data_retention_job_completed",
        tasks_nulled=tasks_nulled,
        chroma_deleted=chroma_deleted,
        conv_deleted=conv_deleted,
        status=status,
    )
