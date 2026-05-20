import asyncio
import time
from typing import Dict, Any, List
import structlog

from workers.base_worker import BaseWorker
from core.rag import embed_text, get_or_create_collection
from core.config import settings
from core.token_tracker import increment_tavily_counter, get_tavily_count
from prompts.templates import RESEARCH_SYSTEM_PROMPT, RESEARCH_USER_TEMPLATE

logger = structlog.get_logger(__name__)


class ResearchWorker(BaseWorker):
    WORKER_NAME = "research"
    QUEUE_CHANNEL = "research_tasks"
    BACKUP_CHANNEL = "research_tasks_backup"

    def get_work_description(self, message: dict) -> str:
        topic = message.get("payload", {}).get("instruction", "topic")[:80]
        return f"Researching: {topic}"

    async def process(self, message: dict, log) -> Dict[str, Any]:
        task_id = message["task_id"]
        dag_node_id = message.get("dag_node_id", "")
        user_id = message["user_id"]
        correlation_id = message["correlation_id"]
        payload = message["payload"]
        instruction = payload["instruction"]

        # Check ChromaDB cache first (similar research, <24h)
        cached = await self._check_research_cache(instruction, user_id, log)
        if cached:
            log.info("research_cache_hit")
            return {
                "chroma_doc_id": cached["doc_id"],
                "summary": cached["summary"],
                "cached": True,
            }

        # Gather search results
        search_results = await self._perform_search(instruction, log)

        if not search_results:
            raise ValueError("No search results obtained from any source")

        # Summarize using Gemini
        search_text = "\n\n".join([
            f"Source: {r.get('url', 'N/A')}\nTitle: {r.get('title', 'N/A')}\nContent: {r.get('content', r.get('snippet', ''))}"
            for r in search_results[:5]
        ])

        summary = await self.call_llm(
            prompt=RESEARCH_USER_TEMPLATE.format(
                topic=instruction,
                search_results=search_text,
            ),
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            max_tokens=800,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        # Store in ChromaDB
        doc_id = f"research_{task_id}_{dag_node_id}"
        embedding = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embed_text(summary)
        )

        collection = get_or_create_collection("task_outputs")
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "agent_role": "research",
                "instruction": instruction[:200],
                "created_at": time.time(),
            }]
        )

        log.info("research_complete", doc_id=doc_id, summary_length=len(summary))

        return {
            "chroma_doc_id": doc_id,
            "summary": summary[:200] + "..." if len(summary) > 200 else summary,
            "full_summary": summary,
        }

    async def _check_research_cache(self, instruction: str, user_id: str, log) -> Dict | None:
        """Check for cached research with high similarity."""
        try:
            loop = asyncio.get_event_loop()
            query_embedding = await loop.run_in_executor(None, lambda: embed_text(instruction))

            collection = get_or_create_collection("task_outputs")
            cutoff = time.time() - (settings.research_cache_age_hours * 3600)

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=1,
                where={
                    "$and": [
                        {"user_id": user_id},
                        {"agent_role": "research"},
                        {"created_at": {"$gt": cutoff}},
                    ]
                },
                include=["documents", "distances", "metadatas"],
            )

            if results["documents"] and results["documents"][0]:
                distance = results["distances"][0][0]
                similarity = 1 - distance
                if similarity >= settings.research_cache_similarity_threshold:
                    return {
                        "doc_id": results["ids"][0][0],
                        "summary": results["documents"][0][0][:200],
                    }
        except Exception as e:
            log.warning("research_cache_check_failed", error=str(e))
        return None

    async def _perform_search(self, query: str, log) -> List[Dict]:
        """Try Tavily → DuckDuckGo → return empty list."""
        # Check Tavily counter
        tavily_count = await get_tavily_count()
        use_tavily = tavily_count < settings.tavily_monthly_limit and bool(settings.tavily_api_key)

        if use_tavily:
            try:
                results = await asyncio.wait_for(
                    self._search_tavily(query),
                    timeout=30,
                )
                if results:
                    await increment_tavily_counter()
                    log.info("research_tavily_success", result_count=len(results))
                    return results
            except asyncio.TimeoutError:
                log.warning("tavily_timeout")
            except Exception as e:
                log.warning("tavily_failed", error=str(e))

        # Fallback to DuckDuckGo
        try:
            results = await asyncio.wait_for(
                self._search_duckduckgo(query),
                timeout=30,
            )
            log.info("research_duckduckgo_success", result_count=len(results))
            return results
        except asyncio.TimeoutError:
            log.warning("duckduckgo_timeout")
        except Exception as e:
            log.warning("duckduckgo_failed", error=str(e))

        # Final fallback: try lower-threshold ChromaDB cache
        try:
            loop = asyncio.get_event_loop()
            query_embedding = await loop.run_in_executor(None, lambda: embed_text(query))
            collection = get_or_create_collection("task_outputs")
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=1,
                where={"agent_role": "research"},
                include=["documents"],
            )
            if results["documents"] and results["documents"][0]:
                log.info("research_used_chroma_fallback")
                return [{"content": results["documents"][0][0], "url": "cached", "title": "Cached research"}]
        except Exception:
            pass

        return []

    async def _search_tavily(self, query: str) -> List[Dict]:
        """Search using Tavily API."""
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.search(query, max_results=5, search_depth="basic")
        )

        results = []
        seen_urls = set()
        for r in response.get("results", []):
            url = r.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "content": r.get("content", ""),
                })
        return results

    async def _search_duckduckgo(self, query: str) -> List[Dict]:
        """Search using DuckDuckGo (free, no API key)."""
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                }
            )
            data = response.json()

        results = []
        # Abstract
        if data.get("Abstract"):
            results.append({
                "url": data.get("AbstractURL", ""),
                "title": data.get("Heading", ""),
                "content": data.get("Abstract", ""),
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:4]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "url": topic.get("FirstURL", ""),
                    "title": topic.get("Text", "")[:100],
                    "content": topic.get("Text", ""),
                })

        return results


if __name__ == "__main__":
    import asyncio
    worker = ResearchWorker()
    asyncio.run(worker.start())
