import asyncio
import json
import re
import time
from typing import Dict, Any, List
import structlog

from workers.base_worker import BaseWorker
from core.rag import embed_text, get_or_create_collection
from prompts.templates import ANALYTICS_RECOMMENDATIONS_PROMPT

logger = structlog.get_logger(__name__)


class AnalyticsWorker(BaseWorker):
    WORKER_NAME = "analytics"
    QUEUE_CHANNEL = "analytics_tasks"
    BACKUP_CHANNEL = "analytics_tasks_backup"

    def get_work_description(self, message: dict) -> str:
        return "Computing engagement score and generating recommendations"

    async def process(self, message: dict, log) -> Dict[str, Any]:
        task_id = message["task_id"]
        dag_node_id = message.get("dag_node_id", "")
        user_id = message["user_id"]
        correlation_id = message["correlation_id"]
        payload = message["payload"]
        instruction = payload["instruction"]

        # Retrieve all prior outputs from ChromaDB
        all_outputs = await self._collect_all_outputs(task_id, log)

        # Deterministic scoring (zero Gemini calls)
        scores = self._compute_scores(all_outputs)
        total_score = sum(scores.values())
        category = self._get_category(total_score)

        # Get 3 AI recommendations (1 Gemini call)
        business_context = " ".join(all_outputs)[:500]
        task_type = message.get("task_type", "business_automation")

        rec_prompt = ANALYTICS_RECOMMENDATIONS_PROMPT.format(
            score=total_score,
            category=category,
            task_type=task_type,
            business_context=business_context,
        )

        rec_response = await self.call_llm(
            prompt=rec_prompt,
            max_tokens=800,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        # Parse recommendations JSON
        recommendations = self._parse_recommendations(rec_response, log)

        analytics_report = {
            "engagement_score": total_score,
            "score_category": category,
            "score_breakdown": scores,
            "recommendations": recommendations,
            "content_word_count": len(" ".join(all_outputs).split()),
            "outputs_analyzed": len(all_outputs),
        }

        # Store in ChromaDB
        doc_id = f"analytics_{task_id}_{dag_node_id}"
        report_text = json.dumps(analytics_report)
        embedding = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embed_text(report_text)
        )
        collection = get_or_create_collection("task_outputs")
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[report_text],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "agent_role": "analytics",
                "engagement_score": total_score,
                "created_at": time.time(),
            }]
        )

        log.info(
            "analytics_complete",
            score=total_score,
            category=category,
            doc_id=doc_id,
        )

        return {
            "chroma_doc_id": doc_id,
            "summary": f"Engagement Score: {total_score}/100 ({category})",
            "analytics_report": analytics_report,
        }

    def _compute_scores(self, outputs: List[str]) -> Dict[str, int]:
        """Deterministic scoring - no AI calls."""
        combined = " ".join(outputs)
        word_count = len(combined.split())

        # 1. Content Length Score (0-20)
        if word_count >= 500:
            length_score = 20
        elif word_count >= 300:
            length_score = 15
        elif word_count >= 150:
            length_score = 10
        elif word_count >= 50:
            length_score = 5
        else:
            length_score = 0

        # 2. Keyword Density Score (0-20)
        business_keywords = [
            "strategy", "revenue", "growth", "customer", "market", "brand",
            "engagement", "conversion", "ROI", "value", "solution", "target",
            "audience", "campaign", "performance", "analytics", "insight"
        ]
        combined_lower = combined.lower()
        keyword_hits = sum(1 for kw in business_keywords if kw in combined_lower)
        keyword_score = min(20, keyword_hits * 2)

        # 3. Call-to-Action Presence (0 or 20)
        cta_patterns = [
            r"call to action", r"click here", r"contact us", r"get started",
            r"sign up", r"learn more", r"try now", r"schedule", r"book",
            r"download", r"register", r"subscribe", r"buy now", r"\bcta\b"
        ]
        has_cta = any(re.search(p, combined_lower) for p in cta_patterns)
        cta_score = 20 if has_cta else 0

        # 4. Audience Specificity Score (0-20)
        specificity_indicators = [
            r"target audience", r"customer segment", r"demographic",
            r"age group", r"small business", r"enterprise", r"consumer",
            r"b2b", r"b2c", r"millennial", r"professional", r"industry"
        ]
        spec_hits = sum(1 for p in specificity_indicators if re.search(p, combined_lower))
        specificity_score = min(20, spec_hits * 4)

        # 5. Competitive Differentiation (0-20)
        diff_indicators = [
            r"unique", r"differentiat", r"competitive advantage", r"unlike",
            r"better than", r"leading", r"innovative", r"exclusive", r"stand out",
            r"our approach", r"why us", r"value proposition"
        ]
        diff_hits = sum(1 for p in diff_indicators if re.search(p, combined_lower))
        diff_score = min(20, diff_hits * 4)

        return {
            "content_length": length_score,
            "keyword_density": keyword_score,
            "call_to_action": cta_score,
            "audience_specificity": specificity_score,
            "competitive_differentiation": diff_score,
        }

    def _get_category(self, score: int) -> str:
        if score >= 70:
            return "High"
        elif score >= 40:
            return "Medium"
        else:
            return "Low"

    def _parse_recommendations(self, response: str, log) -> List[Dict]:
        """Parse Gemini recommendations JSON."""
        try:
            clean = response.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                clean = parts[1] if len(parts) > 1 else clean
                if clean.startswith("json"):
                    clean = clean[4:]
            return json.loads(clean.strip())
        except Exception as e:
            log.warning("recommendations_parse_failed", error=str(e))
            # Return default recommendations
            return [
                {
                    "title": "Enhance Content Depth",
                    "rationale": "More detailed content improves engagement",
                    "action": "Add specific data points and case studies to your content"
                },
                {
                    "title": "Strengthen Call-to-Action",
                    "rationale": "Clear CTAs drive conversion rates",
                    "action": "Add a specific, urgent call-to-action to each section"
                },
                {
                    "title": "Target Audience Refinement",
                    "rationale": "Specific targeting improves relevance",
                    "action": "Define and address specific customer segments explicitly"
                }
            ]

    async def _collect_all_outputs(self, task_id: str, log) -> List[str]:
        """Retrieve all subtask outputs for this task from ChromaDB."""
        try:
            collection = get_or_create_collection("task_outputs")
            results = collection.get(
                where={"task_id": task_id},
                include=["documents"],
            )
            return results.get("documents", [])
        except Exception as e:
            log.warning("output_collection_failed", error=str(e))
            return []


if __name__ == "__main__":
    import asyncio
    worker = AnalyticsWorker()
    asyncio.run(worker.start())
