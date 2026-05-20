import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
import structlog
from sqlalchemy import update

from workers.base_worker import BaseWorker
from models.database import EmailRecord, DAGNode, AsyncSessionLocal
from core.rag import embed_text, get_or_create_collection
from core.token_tracker import increment_resend_counter, get_resend_count
from core.config import settings
from prompts.templates import EMAIL_SYSTEM_PROMPT, EMAIL_USER_TEMPLATE

logger = structlog.get_logger(__name__)


class EmailWorker(BaseWorker):
    WORKER_NAME = "email"
    QUEUE_CHANNEL = "email_tasks"
    BACKUP_CHANNEL = "email_tasks_backup"

    def get_work_description(self, message: dict) -> str:
        return "Generating and sending business email"

    async def process(self, message: dict, log) -> Dict[str, Any]:
        task_id = message["task_id"]
        dag_node_id = message.get("dag_node_id", "")
        user_id = message["user_id"]
        correlation_id = message["correlation_id"]
        payload = message["payload"]
        instruction = payload["instruction"]

        # Retrieve content output
        content_summary = await self._get_content_output(task_id, log)

        recipient_email = payload.get("recipient_email", "")
        purpose = payload.get("purpose", instruction)
        tone = payload.get("tone", "professional")

        # Generate email
        prompt = EMAIL_USER_TEMPLATE.format(
            content_summary=content_summary,
            recipient_email=recipient_email or "the recipient",
            purpose=purpose,
            tone=tone,
        )

        email_text = await self.call_llm(
            prompt=prompt,
            system_prompt=EMAIL_SYSTEM_PROMPT,
            max_tokens=1500,
            task_id=task_id,
            dag_node_id=dag_node_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        # Parse email sections
        email_parts = self._parse_email(email_text)

        if not email_parts["subject"]:
            raise ValueError("Generated email missing subject line")

        # Attempt delivery if recipient provided
        delivery_status = "UNSENT"
        sent_via = None
        sent_at = None

        if recipient_email:
            delivery_status, sent_via = await self._send_email(
                recipient=recipient_email,
                subject=email_parts["subject"],
                body=email_parts["body"],
                log=log,
            )
            if delivery_status == "SENT":
                sent_at = datetime.now(timezone.utc)

        # Store email record
        async with AsyncSessionLocal() as db:
            record = EmailRecord(
                dag_node_id=dag_node_id,
                user_id=user_id,
                recipient_email=recipient_email or "not-provided@placeholder.com",
                subject=email_parts["subject"],
                body=email_parts["body"],
                delivery_status=delivery_status,
                sent_via=sent_via,
                sent_at=sent_at,
            )
            db.add(record)
            await db.commit()

        # Store email content in ChromaDB
        doc_id = f"email_{task_id}_{dag_node_id}"
        full_email = f"Subject: {email_parts['subject']}\n\n{email_text}"
        embedding = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embed_text(full_email)
        )
        collection = get_or_create_collection("task_outputs")
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[full_email],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "agent_role": "email",
                "delivery_status": delivery_status,
                "created_at": time.time(),
            }]
        )

        log.info(
            "email_complete",
            delivery_status=delivery_status,
            sent_via=sent_via,
            doc_id=doc_id,
        )

        return {
            "chroma_doc_id": doc_id,
            "summary": f"Email '{email_parts['subject']}' - {delivery_status}",
            "email_subject": email_parts["subject"],
            "email_body": email_parts["body"],
            "delivery_status": delivery_status,
            "sent_via": sent_via,
            "full_email": email_text,
        }

    def _parse_email(self, email_text: str) -> Dict[str, str]:
        """Parse structured email sections."""
        parts = {
            "subject": "",
            "greeting": "",
            "body": "",
            "cta": "",
            "signature": "",
        }

        section_patterns = {
            "subject": r"\[SUBJECT\](.*?)(?=\[|$)",
            "greeting": r"\[GREETING\](.*?)(?=\[|$)",
            "body": r"\[BODY\](.*?)(?=\[|$)",
            "cta": r"\[CTA\](.*?)(?=\[|$)",
            "signature": r"\[SIGNATURE\](.*?)(?=\[|$)",
        }

        for key, pattern in section_patterns.items():
            match = re.search(pattern, email_text, re.DOTALL | re.IGNORECASE)
            if match:
                parts[key] = match.group(1).strip()

        # If no structured format found, use full text as body
        if not any(parts.values()):
            lines = email_text.strip().split("\n")
            if lines:
                parts["subject"] = lines[0].replace("Subject:", "").strip()
                parts["body"] = "\n".join(lines[1:]).strip()

        return parts

    async def _send_email(self, recipient: str, subject: str, body: str, log) -> Tuple[str, Optional[str]]:
        """Try Resend → EmailJS. Returns (status, provider)."""
        # Try Resend first
        resend_count = await get_resend_count()
        if resend_count < settings.resend_daily_limit and settings.resend_api_key:
            try:
                sent = await asyncio.wait_for(
                    self._send_via_resend(recipient, subject, body),
                    timeout=30,
                )
                if sent:
                    await increment_resend_counter()
                    return "SENT", "resend"
            except asyncio.TimeoutError:
                log.warning("resend_timeout")
            except Exception as e:
                log.warning("resend_failed", error=str(e))

        # Try EmailJS as fallback
        if settings.emailjs_service_id:
            try:
                sent = await asyncio.wait_for(
                    self._send_via_emailjs(recipient, subject, body),
                    timeout=30,
                )
                if sent:
                    return "SENT", "emailjs"
            except asyncio.TimeoutError:
                log.warning("emailjs_timeout")
            except Exception as e:
                log.warning("emailjs_failed", error=str(e))

        return "UNSENT", None

    async def _send_via_resend(self, recipient: str, subject: str, body: str) -> bool:
        """Send email via Resend API."""
        import resend
        resend.api_key = settings.resend_api_key

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: resend.Emails.send({
                "from": "AI Platform <noreply@resend.dev>",
                "to": recipient,
                "subject": subject,
                "text": body,
            })
        )
        return bool(response.get("id"))

    async def _send_via_emailjs(self, recipient: str, subject: str, body: str) -> bool:
        """Send email via EmailJS HTTP API."""
        import httpx

        payload = {
            "service_id": settings.emailjs_service_id,
            "template_id": settings.emailjs_template_id,
            "user_id": settings.emailjs_public_key,
            "template_params": {
                "to_email": recipient,
                "subject": subject,
                "message": body,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.emailjs.com/api/v1.0/email/send",
                json=payload,
                timeout=25,
            )
        return response.status_code == 200

    async def _get_content_output(self, task_id: str, log) -> str:
        """Retrieve content worker output from ChromaDB."""
        try:
            collection = get_or_create_collection("task_outputs")
            results = collection.get(
                where={
                    "$and": [
                        {"task_id": task_id},
                        {"agent_role": "content"},
                    ]
                },
                include=["documents"],
            )
            if results["documents"]:
                return results["documents"][0][:2000]
        except Exception as e:
            log.warning("content_retrieval_failed", error=str(e))
        return "No content available."


if __name__ == "__main__":
    import asyncio
    worker = EmailWorker()
    asyncio.run(worker.start())
