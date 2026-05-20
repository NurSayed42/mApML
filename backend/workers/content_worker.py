import asyncio
import re
import time
from typing import Dict, Any
import structlog

from workers.base_worker import BaseWorker
from core.rag import embed_text, get_or_create_collection
from core.memory import retrieve_long_term_memory, format_long_term_context
from prompts.templates import CONTENT_SYSTEM_PROMPT, CONTENT_TEMPLATES

logger = structlog.get_logger(__name__)

MIN_WORD_COUNT = 200
REQUIRED_HEADERS = ["##"]


class ContentWorker(BaseWorker):
    WORKER_NAME = "content"
    QUEUE_CHANNEL = "content_tasks"
    BACKUP_CHANNEL = "content_tasks_backup"

    def get_work_description(self, message: dict) -> str:
        task_type = message.get("task_type", "content")
        return f"Generating {task_type.replace('_', ' ')}"

    async def process(self, message: dict, log) -> Dict[str, Any]:
        task_id = message["task_id"]
        dag_node_id = message.get("dag_node_id", "")
        user_id = message["user_id"]
        correlation_id = message["correlation_id"]
        payload = message["payload"]
        instruction = payload["instruction"]
        task_type = message.get("task_type", "generic")

        # Retrieve research output from ChromaDB
        research_summary = await self._get_research_output(task_id, user_id, log)

        # Retrieve long-term memory
        memory_context = ""
        try:
            ltm_collection = get_or_create_collection("long_term_memory")
            memories = await retrieve_long_term_memory(
                user_id=user_id,
                query_text=instruction,
                embedding_fn=lambda t: embed_text(t),
                chroma_collection=ltm_collection,
                top_k=3,
            )
            memory_context = format_long_term_context(memories)
        except Exception as e:
            log.warning("ltm_retrieval_failed", error=str(e))

        # Select appropriate template
        template_key = self._select_template(task_type, instruction)
        template = CONTENT_TEMPLATES.get(template_key, CONTENT_TEMPLATES["generic"])

        # Build prompt
        prompt = template.format(
            instruction=instruction,
            business_description=payload.get("business_description", instruction),
            target_audience=payload.get("target_audience", "general business audience"),
            goals=payload.get("goals", "increase engagement and conversion"),
            research_summary=research_summary,
            memory_context=memory_context,
            topic=payload.get("topic", instruction),
            scope=payload.get("scope", "comprehensive"),
            purpose=payload.get("purpose", instruction),
            recipient=payload.get("recipient", "business stakeholders"),
            key_points=payload.get("key_points", instruction),
            platform=payload.get("platform", "all social media"),
            duration=payload.get("duration", "4 weeks"),
            section=payload.get("section", "business overview"),
        )

        # Generate content (with one retry on validation failure)
        content = await self._generate_with_validation(
            prompt=prompt,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
            log=log,
        )

        # Store in ChromaDB
        doc_id = f"content_{task_id}_{dag_node_id}"
        embedding = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embed_text(content)
        )

        collection = get_or_create_collection("task_outputs")
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "agent_role": "content",
                "task_type": task_type,
                "created_at": time.time(),
            }]
        )

        log.info("content_generated", doc_id=doc_id, word_count=len(content.split()))

        return {
            "chroma_doc_id": doc_id,
            "summary": content[:300] + "..." if len(content) > 300 else content,
            "full_content": content,
            "task_type": task_type,
        }

    async def _generate_with_validation(
        self, prompt: str, task_id: str, dag_node_id: str, user_id: str, correlation_id: str, log
    ) -> str:
        """Generate content and validate, retry once if invalid."""
        content = await self.call_llm(
            prompt=prompt,
            system_prompt=CONTENT_SYSTEM_PROMPT,
            max_tokens=3000,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        if self._validate_content(content):
            return content

        # Retry with refinement prompt
        log.warning("content_validation_failed_retrying")
        refined_prompt = f"""The previous response didn't meet requirements. Regenerate with:
- Minimum 200 words
- Use ## for section headers
- Professional business tone
- Specific and actionable content

Original request: {prompt[:500]}

Generate improved content:"""

        content = await self.call_llm(
            prompt=refined_prompt,
            system_prompt=CONTENT_SYSTEM_PROMPT,
            max_tokens=3000,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        return content  # Use even if second attempt doesn't fully validate

    def _validate_content(self, content: str) -> bool:
        """Validate content meets minimum requirements."""
        word_count = len(content.split())
        has_headers = "##" in content
        return word_count >= MIN_WORD_COUNT and has_headers

    async def _get_research_output(self, task_id: str, user_id: str, log) -> str:
        """Retrieve research output from ChromaDB."""
        try:
            collection = get_or_create_collection("task_outputs")
            results = collection.get(
                where={
                    "$and": [
                        {"task_id": task_id},
                        {"agent_role": "research"},
                    ]
                },
                include=["documents"],
            )
            if results["documents"]:
                return results["documents"][0]
        except Exception as e:
            log.warning("research_retrieval_failed", error=str(e))
        return "No research data available."

    def _select_template(self, task_type: str, instruction: str) -> str:
        """Select the most appropriate content template."""
        instruction_lower = instruction.lower()

        if "marketing" in instruction_lower or "campaign" in instruction_lower:
            return "marketing_strategy"
        elif "email" in instruction_lower or "letter" in instruction_lower:
            return "email_draft"
        elif "report" in instruction_lower or "analysis" in instruction_lower:
            return "report"
        elif "social media" in instruction_lower or "content calendar" in instruction_lower:
            return "content_calendar"
        elif "business plan" in instruction_lower:
            return "business_plan"
        else:
            return task_type if task_type in CONTENT_TEMPLATES else "generic"


if __name__ == "__main__":
    import asyncio
    worker = ContentWorker()
    asyncio.run(worker.start())
