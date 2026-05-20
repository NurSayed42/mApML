"""
Multi-provider LLM client using freeflow-llm with Groq → Mistral → Gemini fallback.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Optional

import structlog
from freeflow_llm import FreeFlowClient
from freeflow_llm.config import DEFAULT_MODELS
from freeflow_llm.exceptions import NoProvidersAvailableError
from freeflow_llm.providers import GeminiProvider, GroqProvider

from core.config import settings
from core.llm_providers.mistral import MistralProvider

logger = structlog.get_logger(__name__)

_client_lock = threading.Lock()
_llm_client: Optional[FreeFlowClient] = None


def _sync_env_keys() -> None:
    """Ensure freeflow-llm can read keys from pydantic settings via os.environ."""
    if settings.groq_api_key:
        os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    if settings.gemini_api_key:
        os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    if settings.mistral_api_key:
        os.environ.setdefault("MISTRAL_API_KEY", settings.mistral_api_key)


def build_providers() -> list:
    """
    Build provider chain: Groq (fastest) → Mistral → Gemini.
    Skips providers without API keys.
    """
    providers = []

    if settings.groq_api_key:
        providers.append(GroqProvider(api_key=settings.groq_api_key))
    if settings.mistral_api_key:
        providers.append(MistralProvider(api_key=settings.mistral_api_key))
    if settings.gemini_api_key:
        providers.append(GeminiProvider(api_key=settings.gemini_api_key))

    return [p for p in providers if p.is_available()]


def get_llm_client() -> FreeFlowClient:
    """Return a singleton FreeFlowClient with configured providers."""
    global _llm_client
    with _client_lock:
        if _llm_client is None:
            _sync_env_keys()
            providers = build_providers()
            if not providers:
                raise NoProvidersAvailableError(
                    "No LLM providers configured. Set GROQ_API_KEY, MISTRAL_API_KEY, "
                    "and/or GEMINI_API_KEY in .env"
                )
            _llm_client = FreeFlowClient(providers=providers, verbose=False)
            logger.info(
                "llm_client_initialized",
                providers=[p.name for p in providers],
            )
        return _llm_client


def reset_llm_client() -> None:
    """Close and reset the client (for tests)."""
    global _llm_client
    with _client_lock:
        if _llm_client is not None:
            try:
                _llm_client.close()
            except Exception:
                pass
            _llm_client = None


def build_messages(
    prompt: str,
    system_prompt: Optional[str] = None,
    history: Optional[list] = None,
) -> list[dict[str, str]]:
    """Convert prompt/system/history into OpenAI-style chat messages."""
    messages: list[dict[str, str]] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if history:
        for msg in history:
            role = msg.get("role", "user")
            if role == "model":
                role = "assistant"

            content = ""
            if "parts" in msg and msg["parts"]:
                part = msg["parts"][0]
                content = part.get("text", "") if isinstance(part, dict) else str(part)
            elif "content" in msg:
                content = str(msg["content"])

            if content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})
    return messages


def chat_completion_sync(
    prompt: str,
    system_prompt: Optional[str] = None,
    history: Optional[list] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """
    Synchronous chat with automatic provider fallback.
    Returns dict with content, provider, model, and usage fields.
    """
    client = get_llm_client()
    messages = build_messages(prompt, system_prompt, history)

    response = client.chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
    )

    usage = response.usage
    return {
        "content": response.content or "",
        "provider": response.provider or "unknown",
        "model": response.model or model or "",
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }


async def chat_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    history: Optional[list] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    model: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Async wrapper around freeflow-llm (runs sync client in a thread pool)."""
    timeout = timeout_seconds or settings.llm_request_timeout_seconds
    loop = asyncio.get_event_loop()

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: chat_completion_sync(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    history=history,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model,
                ),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as e:
        raise TimeoutError(
            f"LLM request timed out after {timeout}s (providers: "
            f"{get_llm_client().list_providers()})"
        ) from e
    except NoProvidersAvailableError:
        raise
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            logger.warning("llm_rate_limited_all_providers", error=str(e))
        raise


def list_configured_providers() -> list[str]:
    """List provider names that have API keys configured."""
    names = []
    if settings.groq_api_key:
        names.append("groq")
    if settings.mistral_api_key:
        names.append("mistral")
    if settings.gemini_api_key:
        names.append("gemini")
    return names


def get_default_model(provider: str) -> str:
    return DEFAULT_MODELS.get(provider, "default")
