import asyncio
import json
import uuid
import traceback
from datetime import datetime, timezone, timedelta
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import DAGNode, Task, AgentError, AsyncSessionLocal
from core.locks import connect_redis, DistributedLock
from core.config import settings
from core.token_tracker import log_token_usage
from core.sse import push_sse_event, build_event
from core.uuid_utils import parse_uuid
from core.llm_client import chat_completion
from freeflow_llm.exceptions import NoProvidersAvailableError

logger = structlog.get_logger(__name__)


class BaseWorker(ABC):
    WORKER_NAME: str = "base"
    QUEUE_CHANNEL: str = "base_tasks"
    BACKUP_CHANNEL: str = "base_tasks_backup"

    def __init__(self):
        self.redis = None
        self.running = True
        self.log = structlog.get_logger(self.__class__.__name__)

    async def start(self):
        self.log.info(
            "worker_starting",
            worker=self.WORKER_NAME,
            queue=self.QUEUE_CHANNEL,
            backup=self.BACKUP_CHANNEL,
        )
        try:
            self.redis = await connect_redis()
        except ConnectionError as e:
            self.log.error("redis_connection_failed", worker=self.WORKER_NAME, error=str(e))
            raise

        drained = await self._drain_backup_list()
        self.log.info(
            "worker_ready",
            worker=self.WORKER_NAME,
            backup_messages_drained=drained,
            listening_on=self.QUEUE_CHANNEL,
        )

        idle_polls = 0
        while self.running:
            try:
                got_message = await self._process_next()
                if not got_message:
                    idle_polls += 1
                    if idle_polls == 1 or idle_polls % 12 == 0:
                        self.log.info(
                            "worker_idle_waiting",
                            worker=self.WORKER_NAME,
                            queue=self.QUEUE_CHANNEL,
                            polls=idle_polls,
                            hint="Submit a task via POST /api/v1/tasks to enqueue work",
                        )
            except ConnectionError as e:
                self.log.error("redis_connection_lost", worker=self.WORKER_NAME, error=str(e))
                await asyncio.sleep(5)
                try:
                    self.redis = await connect_redis()
                except ConnectionError:
                    pass
            except Exception as e:
                self.log.error("worker_loop_error", worker=self.WORKER_NAME, error=str(e))
                await asyncio.sleep(5)

    async def _drain_backup_list(self) -> int:
        """Move stranded messages from backup list back to the work queue."""
        drained = 0
        max_messages = settings.worker_backup_drain_max_messages

        while drained < max_messages:
            try:
                msg = await asyncio.wait_for(
                    self.redis.rpoplpush(self.BACKUP_CHANNEL, self.QUEUE_CHANNEL),
                    timeout=settings.redis_socket_timeout_seconds,
                )
            except asyncio.TimeoutError:
                self.log.error(
                    "backup_drain_timeout",
                    worker=self.WORKER_NAME,
                    backup=self.BACKUP_CHANNEL,
                    drained=drained,
                )
                break

            if msg is None:
                break
            if not str(msg).strip():
                self.log.warning(
                    "backup_empty_message_skipped",
                    worker=self.WORKER_NAME,
                )
                continue

            drained += 1
            self.log.info(
                "backup_message_requeued",
                worker=self.WORKER_NAME,
                drained=drained,
            )

        if drained >= max_messages:
            self.log.error(
                "backup_drain_limit_reached",
                worker=self.WORKER_NAME,
                max_messages=max_messages,
            )

        return drained

    async def _process_next(self) -> bool:
        """Returns True if a message was received and processed."""
        try:
            raw = await asyncio.wait_for(
                self.redis.brpoplpush(
                    self.QUEUE_CHANNEL,
                    self.BACKUP_CHANNEL,
                    timeout=settings.worker_queue_poll_timeout_seconds,
                ),
                timeout=settings.worker_queue_poll_timeout_seconds + 2,
            )
        except asyncio.TimeoutError:
            self.log.warning(
                "queue_poll_timeout",
                worker=self.WORKER_NAME,
                queue=self.QUEUE_CHANNEL,
            )
            return False

        if raw is None:
            return False

        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            self.log.error("invalid_message_format", worker=self.WORKER_NAME)
            await self.redis.lrem(self.BACKUP_CHANNEL, 1, raw)
            return True

        task_id = message.get("task_id")
        dag_node_id = message.get("dag_node_id")
        correlation_id = message.get("correlation_id", str(uuid.uuid4()))

        log = self.log.bind(
            task_id=task_id,
            dag_node_id=dag_node_id,
            correlation_id=correlation_id,
            worker=self.WORKER_NAME,
        )

        # Check retry_after
        retry_after_str = message.get("retry_after")
        if retry_after_str:
            retry_after = datetime.fromisoformat(retry_after_str)
            if datetime.now(timezone.utc) < retry_after:
                await self.redis.rpush(self.QUEUE_CHANNEL, raw)
                await self.redis.lrem(self.BACKUP_CHANNEL, 1, raw)
                await asyncio.sleep(1)
                return False

        lock_key = dag_node_id or task_id
        lock = DistributedLock(self.redis, lock_key, settings.worker_lock_ttl_seconds)
        acquired = await lock.acquire()

        if not acquired:
            log.info("lock_not_acquired_requeue")
            await self.redis.rpush(self.QUEUE_CHANNEL, raw)
            await self.redis.lrem(self.BACKUP_CHANNEL, 1, raw)
            return False

        try:
            dag_node_uuid = parse_uuid(dag_node_id)
            async with AsyncSessionLocal() as db:
                if dag_node_uuid:
                    await db.execute(
                        update(DAGNode)
                        .where(DAGNode.id == dag_node_uuid)
                        .values(status="IN_PROGRESS", started_at=datetime.now(timezone.utc))
                    )
                    await db.commit()

            user_id = message.get("user_id", "")
            await push_sse_event(
                user_id,
                build_event(
                    "agent_started",
                    task_id=task_id,
                    correlation_id=correlation_id,
                    data={
                        "agent_name": self.WORKER_NAME,
                        "task_type": message.get("task_type", ""),
                        "description": self.get_work_description(message),
                    }
                )
            )

            start_time = datetime.now(timezone.utc)
            result = await self.process(message, log)
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            async with AsyncSessionLocal() as db:
                if dag_node_uuid:
                    await db.execute(
                        update(DAGNode)
                        .where(DAGNode.id == dag_node_uuid)
                        .values(
                            status="COMPLETED",
                            completed_at=datetime.now(timezone.utc),
                            duration_ms=duration_ms,
                            output_chroma_doc_id=result.get("chroma_doc_id"),
                        )
                    )
                    await db.commit()

            await push_sse_event(
                user_id,
                build_event(
                    "agent_completed",
                    task_id=task_id,
                    correlation_id=correlation_id,
                    data={
                        "agent_name": self.WORKER_NAME,
                        "output_summary": result.get("summary", "Completed"),
                        "duration_ms": duration_ms,
                    }
                )
            )

            completion_event = {
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "parent_task_id": message.get("parent_task_id", task_id),
                "user_id": user_id,
                "correlation_id": correlation_id,
                "agent_role": self.WORKER_NAME,
                "status": "COMPLETED",
                "result": result,
            }
            await self.redis.rpush("task_results", json.dumps(completion_event))

            log.info("worker_task_completed", duration_ms=duration_ms)
            return True

        except Exception as e:
            await self._handle_failure(message, e, log)
            return True
        finally:
            await lock.release()
            await self.redis.lrem(self.BACKUP_CHANNEL, 1, raw)

    async def _handle_failure(self, message: dict, error: Exception, log):
        task_id = message.get("task_id")
        dag_node_id = message.get("dag_node_id")
        correlation_id = message.get("correlation_id", "")
        user_id = message.get("user_id", "")
        retry_count = message.get("retry_count", 0)

        log.error("worker_task_failed", error=str(error), retry_count=retry_count)

        dag_node_uuid = parse_uuid(dag_node_id)
        task_uuid = parse_uuid(task_id)
        correlation_uuid = parse_uuid(correlation_id) if correlation_id else uuid.uuid4()

        async with AsyncSessionLocal() as db:
            agent_error = AgentError(
                dag_node_id=dag_node_uuid,
                task_id=task_uuid,
                correlation_id=correlation_uuid,
                agent_name=self.WORKER_NAME,
                error_type=type(error).__name__,
                error_message=str(error),
                stack_trace=traceback.format_exc(),
                is_in_dlq=retry_count >= 2,
            )
            db.add(agent_error)
            await db.commit()

        if retry_count < 2:
            backoff = settings.retry_backoff_first if retry_count == 0 else settings.retry_backoff_second
            retry_after = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat()
            message["retry_count"] = retry_count + 1
            message["retry_after"] = retry_after

            async with AsyncSessionLocal() as db:
                if dag_node_uuid:
                    await db.execute(
                        update(DAGNode)
                        .where(DAGNode.id == dag_node_uuid)
                        .values(
                            status="QUEUED",
                            retry_count=retry_count + 1,
                            retry_after=datetime.fromisoformat(retry_after),
                            error_message=str(error),
                        )
                    )
                    await db.commit()

            await self.redis.rpush(self.QUEUE_CHANNEL, json.dumps(message))
            log.info("worker_task_requeued", retry_count=retry_count + 1, backoff=backoff)

        else:
            dlq_message = {**message, "final_error": str(error), "worker": self.WORKER_NAME}
            await self.redis.rpush("dead_letter_queue", json.dumps(dlq_message))
            await self.redis.expire("dead_letter_queue", settings.dlq_redis_ttl_hours * 3600)

            async with AsyncSessionLocal() as db:
                if dag_node_uuid:
                    await db.execute(
                        update(DAGNode)
                        .where(DAGNode.id == dag_node_uuid)
                        .values(status="DLQ", error_message=str(error))
                    )
                    await db.commit()

            await self.redis.rpush("task_results", json.dumps({
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "parent_task_id": message.get("parent_task_id", task_id),
                "user_id": user_id,
                "correlation_id": correlation_id,
                "agent_role": self.WORKER_NAME,
                "status": "DLQ",
                "result": {},
            }))

            await push_sse_event(
                user_id,
                build_event(
                    "fallback_activated",
                    task_id=task_id,
                    correlation_id=correlation_id,
                    data={
                        "agent_name": self.WORKER_NAME,
                        "reason": str(error),
                        "user_message": f"The {self.WORKER_NAME} agent encountered an issue. A simplified version will be generated.",
                    }
                )
            )

            log.error("worker_task_moved_to_dlq")

    async def call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None,
        max_tokens: int = 2048,
        task_id: str = "",
        dag_node_id: str = "",
        user_id: str = "",
        correlation_id: str = "",
    ) -> str:
        """
        Call LLM via freeflow-llm (Groq → Mistral → Gemini fallback).
        """
        self.log.info("llm_request_start", worker=self.WORKER_NAME, max_tokens=max_tokens)

        try:
            result = await chat_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                history=history,
                max_tokens=max_tokens,
                temperature=0.7,
            )

            provider = result["provider"]
            model_name = result["model"] or f"{provider}-default"

            self.log.info(
                "llm_request_success",
                worker=self.WORKER_NAME,
                provider=provider,
                model=model_name,
            )

            if result["total_tokens"] > 0:
                await log_token_usage(
                    task_id=task_id,
                    dag_node_id=dag_node_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    agent_name=self.WORKER_NAME,
                    model_name=f"{provider}/{model_name}",
                    prompt_tokens=result["prompt_tokens"],
                    completion_tokens=result["completion_tokens"],
                )

            content = result["content"]
            if not content.strip():
                raise ValueError(f"Empty response from provider {provider}")

            return content

        except NoProvidersAvailableError as e:
            self.log.error("llm_no_providers", worker=self.WORKER_NAME, error=str(e))
            raise
        except TimeoutError as e:
            self.log.error("llm_timeout", worker=self.WORKER_NAME, error=str(e))
            raise
        except Exception as e:
            self.log.error(
                "llm_request_failed",
                worker=self.WORKER_NAME,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def call_gemini(self, *args, **kwargs) -> str:
        """Deprecated alias — use call_llm()."""
        return await self.call_llm(*args, **kwargs)

    def get_work_description(self, message: dict) -> str:
        return f"Processing {message.get('task_type', 'task')}"

    @abstractmethod
    async def process(self, message: dict, log) -> Dict[str, Any]:
        raise NotImplementedError