import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List
import structlog
from sqlalchemy import select, update

from models.database import Task, DAGNode, AsyncSessionLocal
from core.dag import resolve_dependencies_serializable, are_all_nodes_terminal
from core.uuid_utils import parse_uuid
from core.llm_client import chat_completion
from core.rag import embed_text, get_or_create_collection
from core.sse import push_sse_event, build_event
from core.locks import get_redis
from core.memory import store_long_term_memory
from prompts.templates import FALLBACK_CONTENT_PROMPT

logger = structlog.get_logger(__name__)


class AggregatorWorker:
    """
    Aggregator Worker: subscribes to task_results, resolves dependencies,
    assembles final output when all nodes are terminal.
    Does NOT extend BaseWorker - uses pub/sub pattern instead of BRPOPLPUSH.
    """
    WORKER_NAME = "aggregator"

    def __init__(self):
        self.redis = None
        self.running = True
        self.log = structlog.get_logger("AggregatorWorker")

    async def start(self):
        """Start the aggregator event loop."""
        self.log.info("aggregator_starting")
        self.redis = await get_redis()
        await self._drain_backup_list()

        # On restart: resume monitoring in-progress tasks
        await self._resume_in_progress_tasks()

        # Main event loop
        while self.running:
            try:
                await self._process_next_result()
            except Exception as e:
                self.log.error("aggregator_loop_error", error=str(e))
                await asyncio.sleep(5)

    async def _drain_backup_list(self):
        while True:
            msg = await self.redis.rpoplpush("task_results_backup", "task_results")
            if msg is None:
                break
            self.log.info("aggregator_backup_message_requeued")

    async def _resume_in_progress_tasks(self):
        """On restart, find all tasks in progress and resume monitoring."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Task).where(Task.status.in_(["PLANNED", "IN_PROGRESS"]))
            )
            in_progress = result.scalars().all()

        self.log.info("resuming_in_progress_tasks", count=len(in_progress))

        for task in in_progress:
            # Check if already fully done
            async with AsyncSessionLocal() as db:
                all_done, nodes = await are_all_nodes_terminal(db, str(task.id))

            if all_done:
                await self._assemble_final_output(str(task.id), str(task.user_id), str(task.correlation_id))

    async def _process_next_result(self):
        """Listen for task completion events on task_results channel."""
        raw = await self.redis.brpoplpush("task_results", "task_results_backup", timeout=5)
        if raw is None:
            return

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            await self.redis.lrem("task_results_backup", 1, raw)
            return

        parent_task_id = event.get("parent_task_id") or event.get("task_id")
        dag_node_id = event.get("dag_node_id")
        user_id = event.get("user_id", "")
        correlation_id = event.get("correlation_id", "")

        log = self.log.bind(
            parent_task_id=parent_task_id,
            dag_node_id=dag_node_id,
            correlation_id=correlation_id,
        )

        processed = False
        try:
            # Run dependency resolution in serializable transaction
            async with AsyncSessionLocal() as db:
                newly_unblocked = await resolve_dependencies_serializable(
                    db, dag_node_id, parent_task_id
                )
                await db.commit()

            # Queue newly unblocked nodes (aggregator is a sentinel — mark complete, do not queue)
            for node in newly_unblocked:
                if node.agent_role == "aggregator":
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(DAGNode)
                            .where(DAGNode.id == node.id)
                            .values(
                                status="COMPLETED",
                                completed_at=datetime.now(timezone.utc),
                            )
                        )
                        await db.commit()
                    log.info("aggregator_sentinel_node_completed")
                    continue

                channel = f"{node.agent_role}_tasks"
                worker_message = {
                    "task_id": parent_task_id,
                    "parent_task_id": parent_task_id,
                    "dag_node_id": str(node.id),
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                    "agent_role": node.agent_role,
                    "task_type": node.task_type,
                    "payload": node.payload,
                    "retry_count": 0,
                }
                await self.redis.rpush(channel, json.dumps(worker_message))
                log.info("node_unblocked_and_queued", agent_role=node.agent_role)

            # Check if all nodes are terminal
            async with AsyncSessionLocal() as db:
                all_done, nodes = await are_all_nodes_terminal(db, parent_task_id)

            if all_done:
                await self._assemble_final_output(parent_task_id, user_id, correlation_id, nodes)

            processed = True

        except Exception as e:
            log.error("aggregator_processing_error", error=str(e))
            await self.redis.rpush("task_results", raw)
        finally:
            if processed:
                await self.redis.lrem("task_results_backup", 1, raw)

    async def _assemble_final_output(
        self,
        task_id: str,
        user_id: str,
        correlation_id: str,
        nodes: List = None,
    ):
        """Assemble final output from all agent outputs."""
        log = self.log.bind(task_id=task_id, correlation_id=correlation_id)

        task_uuid = parse_uuid(task_id)
        async with AsyncSessionLocal() as db:
            existing = await db.execute(select(Task).where(Task.id == task_uuid))
            task_row = existing.scalar_one_or_none()
            if task_row and task_row.status in ("COMPLETED", "FALLBACK"):
                log.info("final_output_already_assembled", status=task_row.status)
                return

        log.info("assembling_final_output")

        # Get all outputs from ChromaDB
        outputs = {}
        try:
            collection = get_or_create_collection("task_outputs")
            results = collection.get(
                where={"task_id": task_id},
                include=["documents", "metadatas"],
            )

            if results["documents"]:
                for doc, meta in zip(results["documents"], results["metadatas"]):
                    role = meta.get("agent_role", "unknown")
                    outputs[role] = doc

        except Exception as e:
            log.error("output_retrieval_failed", error=str(e))

        # Generate fallback for DLQ nodes
        if nodes:
            async with AsyncSessionLocal() as db:
                all_nodes_result = await db.execute(
                    select(DAGNode).where(DAGNode.parent_task_id == task_id)
                )
                all_nodes = all_nodes_result.scalars().all()

            for node in all_nodes:
                if node.status == "DLQ" and node.agent_role not in outputs:
                    fallback = await self._generate_fallback(
                        node.agent_role,
                        node.payload.get("instruction", ""),
                        outputs,
                        task_id,
                        user_id,
                        correlation_id,
                    )
                    outputs[node.agent_role] = f"[Auto-generated summary - original process encountered an error]\n\n{fallback}"

        # Build final output structure
        final_output = {
            "task_id": task_id,
            "sections": {},
            "metadata": {
                "assembled_at": datetime.now(timezone.utc).isoformat(),
                "correlation_id": correlation_id,
                "has_fallback_sections": any(
                    v.startswith("[Auto-generated") for v in outputs.values()
                ),
            }
        }

        # Map agent outputs to structured sections
        section_labels = {
            "research": "Research & Intelligence",
            "content": "Business Content",
            "email": "Email Communication",
            "analytics": "Analytics & Recommendations",
        }

        for role, label in section_labels.items():
            if role in outputs:
                # Try to parse analytics JSON
                if role == "analytics":
                    try:
                        final_output["sections"][label] = json.loads(outputs[role])
                    except Exception:
                        final_output["sections"][label] = outputs[role]
                else:
                    final_output["sections"][label] = outputs[role]

        # Update task status to COMPLETED
        async with AsyncSessionLocal() as db:
            has_fallback = final_output["metadata"]["has_fallback_sections"]
            await db.execute(
                update(Task)
                .where(Task.id == task_uuid)
                .values(
                    status="FALLBACK" if has_fallback else "COMPLETED",
                    final_output=final_output,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        # Store in long-term memory
        try:
            async with AsyncSessionLocal() as db:
                task_result = await db.execute(select(Task).where(Task.id == task_uuid))
                task = task_result.scalar_one_or_none()

            if task:
                summary = " ".join(
                    str(v)[:200] for v in list(outputs.values())[:2]
                )
                ltm_collection = get_or_create_collection("long_term_memory")
                await store_long_term_memory(
                    user_id=user_id,
                    task_id=task_id,
                    task_type=task.title[:50],
                    request_text=task.raw_input[:500],
                    response_summary=summary,
                    embedding_fn=lambda t: embed_text(t),
                    chroma_collection=ltm_collection,
                )
        except Exception as e:
            log.warning("long_term_memory_store_failed", error=str(e))

        # Push SSE task_completed event
        await push_sse_event(
            user_id,
            build_event(
                "task_completed",
                task_id=task_id,
                correlation_id=correlation_id,
                data={"final_output": final_output},
            )
        )

        log.info("final_output_assembled", section_count=len(final_output["sections"]))

    async def _generate_fallback(
        self,
        agent_role: str,
        instruction: str,
        existing_outputs: Dict,
        task_id: str,
        user_id: str,
        correlation_id: str,
    ) -> str:
        """Generate fallback content for a failed agent."""
        context = "\n".join([f"{k}: {v[:200]}" for k, v in existing_outputs.items()])

        try:
            prompt = FALLBACK_CONTENT_PROMPT.format(
                section_type=agent_role,
                instruction=instruction[:300],
                context=context[:500],
            )

            result = await chat_completion(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.7,
            )
            self.log.info(
                "fallback_generated",
                provider=result["provider"],
                model=result["model"],
            )
            return result["content"]
        except Exception as e:
            self.log.error("fallback_generation_failed", error=str(e))
            return f"Unable to generate {agent_role} content. Please review the other sections for your complete output."


if __name__ == "__main__":
    import asyncio
    worker = AggregatorWorker()
    asyncio.run(worker.start())
