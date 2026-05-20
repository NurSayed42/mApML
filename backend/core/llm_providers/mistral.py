"""Mistral provider for freeflow-llm (OpenAI-compatible chat API)."""

import time
from typing import Any, Optional

from freeflow_llm.models import FreeFlowResponse
from freeflow_llm.providers.base import BaseProvider


class MistralProvider(BaseProvider):
    """
    Mistral AI provider (free tier available).

    Default model: mistral-small-latest
    """

    def get_api_base_url(self) -> str:
        return "https://api.mistral.ai/v1"

    def build_request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def build_request_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        top_p: float,
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        json_data: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens or 1024,
        }
        if stream:
            json_data["stream"] = True
        json_data.update(kwargs)
        return "/chat/completions", json_data

    def parse_response(self, response_data: dict[str, Any], model: str) -> FreeFlowResponse:
        return FreeFlowResponse.from_dict(
            {
                "id": response_data.get("id", f"chatcmpl-{int(time.time())}"),
                "object": "chat.completion",
                "created": response_data.get("created", int(time.time())),
                "model": response_data.get("model", model),
                "choices": [
                    {
                        "index": choice.get("index", 0),
                        "message": {
                            "role": choice.get("message", {}).get("role", "assistant"),
                            "content": choice.get("message", {}).get("content", ""),
                        },
                        "finish_reason": choice.get("finish_reason", "stop"),
                    }
                    for choice in response_data.get("choices", [])
                ],
                "usage": (
                    {
                        "prompt_tokens": response_data["usage"]["prompt_tokens"],
                        "completion_tokens": response_data["usage"]["completion_tokens"],
                        "total_tokens": response_data["usage"]["total_tokens"],
                    }
                    if response_data.get("usage")
                    else None
                ),
            },
            provider="mistral",
        )

    def parse_stream_chunk(
        self, chunk_data: dict[str, Any], model: str
    ) -> Optional[FreeFlowResponse]:
        return FreeFlowResponse.from_dict(
            {
                "id": chunk_data.get("id", f"chatcmpl-{int(time.time())}"),
                "object": "chat.completion.chunk",
                "created": chunk_data.get("created", int(time.time())),
                "model": chunk_data.get("model", model),
                "choices": [
                    {
                        "index": choice.get("index", 0),
                        "delta": choice.get("delta", {}),
                        "finish_reason": choice.get("finish_reason"),
                    }
                    for choice in chunk_data.get("choices", [])
                ],
                "usage": None,
            },
            provider="mistral",
        )
