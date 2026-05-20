import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import update

from workers.base_worker import BaseWorker
from models.database import Task, DAGNode, AsyncSessionLocal
from core.dag import create_dag_atomically, get_root_nodes
from core.outbox import create_outbox_record
from core.injection_filter import validate_and_sanitize
from core.sse import push_sse_event, build_event
from core.memory import retrieve_long_term_memory, format_long_term_context
from core.uuid_utils import parse_uuid
from core.rag import embed_text, get_or_create_collection
from prompts.templates import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE


class PlannerWorker(BaseWorker):
    WORKER_NAME = "planner"
    QUEUE_CHANNEL = "planner_tasks"
    BACKUP_CHANNEL = "planner_tasks_backup"

    def get_work_description(self, message: dict) -> str:
        return "Analyzing request and creating execution plan"

    async def process(self, message: dict, log) -> Dict[str, Any]:
        task_id = message["task_id"]
        user_id = message["user_id"]
        correlation_id = message["correlation_id"]
        instruction = message["payload"]["instruction"]
        session_id = message["payload"].get("session_id", "")

        # Input validation already done at API layer, but double-check
        sanitized, is_safe, matched = validate_and_sanitize(instruction, correlation_id, user_id)
        if not is_safe:
            raise ValueError(f"Prompt injection detected in planning stage: {matched}")

        # Retrieve long-term memory context
        memory_context = ""
        try:
            ltm_collection = get_or_create_collection("long_term_memory")
            memories = await retrieve_long_term_memory(
                user_id=user_id,
                query_text=instruction,
                embedding_fn=lambda t: embed_text(t),
                chroma_collection=ltm_collection,
            )
            memory_context = format_long_term_context(memories)
        except Exception as e:
            log.warning("long_term_memory_retrieval_failed", error=str(e))

        # Build planning prompt
        prompt = PLANNER_USER_TEMPLATE.format(
            instruction=sanitized,
            memory_context=memory_context,
        )

        # Call Gemini for task plan
        response_text = await self.call_llm(
            prompt=prompt,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            max_tokens=2000,
            task_id=task_id,
            dag_node_id=message.get("dag_node_id", ""),
            user_id=user_id,
            correlation_id=correlation_id,
        )

        # Parse JSON plan
        try:
            clean = response_text.strip()
            if "```" in clean:
                import re
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", clean)
                if match:
                    clean = match.group(1)
            plan = json.loads(clean.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Gemini returned invalid JSON plan: {e}\nResponse: {response_text[:500]}")

        # Validate plan structure
        if "subtasks" not in plan or not plan["subtasks"]:
            raise ValueError("Plan contains no subtasks")

        subtasks = plan["subtasks"]

        # Add standard aggregator if not present
        has_aggregator = any(s["agent_role"] == "aggregator" for s in subtasks)
        if not has_aggregator:
            non_aggregator_roles = [s["agent_role"] for s in subtasks]
            subtasks.append({
                "agent_role": "aggregator",
                "task_type": "aggregate_results",
                "payload": {
                    "instruction": instruction,
                    "user_id": user_id,
                },
                "dependencies": non_aggregator_roles,
            })

        # Enrich payloads with common fields
        for subtask in subtasks:
            subtask["payload"].update({
                "instruction": instruction,
                "user_id": user_id,
                "session_id": session_id,
                "correlation_id": correlation_id,
            })

        task_uuid = parse_uuid(task_id)

        # Create DAG atomically in PostgreSQL
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Task)
                .where(Task.id == task_uuid)
                .values(title=plan.get("title", instruction[:100]), status="IN_PROGRESS")
            )

            await create_dag_atomically(db, task_uuid, subtasks)
            root_nodes = await get_root_nodes(db, task_uuid)

            for node in root_nodes:
                if node.agent_role == "aggregator":
                    continue
                subtask_def = next(
                    (s for s in subtasks if s["agent_role"] == node.agent_role), None
                )
                if subtask_def is None:
                    continue

                channel = self._get_channel_for_role(node.agent_role)
                worker_message = {
                    "task_id": task_id,
                    "parent_task_id": task_id,
                    "dag_node_id": str(node.id),
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                    "agent_role": node.agent_role,
                    "task_type": node.task_type,
                    "payload": subtask_def["payload"],
                    "retry_count": 0,
                    "idempotency_key": f"{task_id}_{node.agent_role}",
                }

                await create_outbox_record(
                    db=db,
                    task_id=task_id,
                    correlation_id=correlation_id,
                    redis_channel=channel,
                    message=worker_message,
                )

            await db.commit()

        # Push SSE event
        await push_sse_event(
            user_id,
            build_event(
                "planning_complete",
                task_id=task_id,
                correlation_id=correlation_id,
                data={
                    "subtask_count": len(subtasks),
                    "agent_list": [s["agent_role"] for s in subtasks],
                    "title": plan.get("title", ""),
                }
            )
        )

        log.info(
            "planning_complete",
            task_id=task_id,
            subtask_count=len(subtasks),
        )

        return {
            "chroma_doc_id": None,
            "summary": f"Created {len(subtasks)} subtask plan",
        }

    def _get_channel_for_role(self, role: str) -> str:
        channels = {
            "research": "research_tasks",
            "content": "content_tasks",
            "email": "email_tasks",
            "analytics": "analytics_tasks",
            "aggregator": "aggregator_tasks",
        }
        return channels.get(role, f"{role}_tasks")


if __name__ == "__main__":
    import asyncio
    import logging
    import structlog

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

    worker = PlannerWorker()
    asyncio.run(worker.start())
