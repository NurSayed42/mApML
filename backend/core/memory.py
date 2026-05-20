import json
import asyncio
from typing import List, Dict, Optional
import structlog
from core.locks import get_redis
from core.config import settings

logger = structlog.get_logger(__name__)


# ─── Short-Term Session Memory ──────────────────────────────────
async def add_to_session_memory(session_id: str, message: str, response: str):
    """Add a message-response pair to session memory. Capped at 10 pairs."""
    redis = await get_redis()
    key = f"session:{session_id}:messages"
    pair = json.dumps({"message": message, "response": response})
    await redis.rpush(key, pair)
    await redis.ltrim(key, -settings.short_term_memory_limit, -1)
    await redis.expire(key, settings.session_memory_ttl_seconds)


async def get_session_memory(session_id: str) -> List[Dict[str, str]]:
    """Retrieve all session message pairs."""
    redis = await get_redis()
    key = f"session:{session_id}:messages"
    raw = await redis.lrange(key, 0, -1)
    return [json.loads(r) for r in raw]


def format_session_memory_for_gemini(pairs: List[Dict[str, str]]) -> List[Dict]:
    """Format session memory as Gemini messages array."""
    messages = []
    for pair in pairs:
        messages.append({"role": "user", "parts": [{"text": pair["message"]}]})
        messages.append({"role": "model", "parts": [{"text": pair["response"]}]})
    return messages


# ─── Long-Term Semantic Memory ──────────────────────────────────
async def store_long_term_memory(
    user_id: str,
    task_id: str,
    task_type: str,
    request_text: str,
    response_summary: str,
    embedding_fn,
    chroma_collection,
):
    """Store completed task in ChromaDB long-term memory."""
    doc_id = f"ltm_{user_id}_{task_id}"
    text = f"Request: {request_text}\nResponse: {response_summary}"
    embedding = embedding_fn(text)

    try:
        chroma_collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "task_type": task_type,
                "created_at": __import__("time").time(),
            }]
        )
        logger.info("long_term_memory_stored", user_id=user_id, task_id=task_id)
        return doc_id
    except Exception as e:
        logger.error("long_term_memory_store_failed", error=str(e), task_id=task_id)
        return None


async def retrieve_long_term_memory(
    user_id: str,
    query_text: str,
    embedding_fn,
    chroma_collection,
    top_k: int = 3,
    similarity_threshold: float = None,
) -> List[Dict]:
    """Retrieve similar past interactions for a user."""
    if similarity_threshold is None:
        similarity_threshold = settings.long_term_memory_similarity_threshold

    query_embedding = embedding_fn(query_text)

    try:
        results = chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id},
            include=["documents", "distances", "metadatas"],
        )

        memories = []
        if results["documents"] and results["documents"][0]:
            for doc, distance, meta in zip(
                results["documents"][0],
                results["distances"][0],
                results["metadatas"][0],
            ):
                similarity = 1 - distance  # ChromaDB returns L2 distance
                if similarity >= similarity_threshold:
                    memories.append({
                        "text": doc,
                        "similarity": similarity,
                        "task_type": meta.get("task_type", ""),
                        "task_id": meta.get("task_id", ""),
                    })

        logger.info(
            "long_term_memory_retrieved",
            user_id=user_id,
            count=len(memories),
        )
        return memories

    except Exception as e:
        logger.error("long_term_memory_retrieve_failed", error=str(e), user_id=user_id)
        return []


def format_long_term_context(memories: List[Dict]) -> str:
    """Format retrieved memories as a context block for prompts."""
    if not memories:
        return ""

    lines = ["## Relevant Previous Work\n"]
    for i, mem in enumerate(memories, 1):
        lines.append(f"{i}. {mem['text'][:500]}...\n")

    return "\n".join(lines)
