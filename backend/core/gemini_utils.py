from typing import Any, Optional


def extract_text_from_response(response: Any) -> str:
    """Safely read text from a Gemini generate_content response."""
    if response is None:
        raise ValueError("Empty response from Gemini")

    if getattr(response, "candidates", None):
        candidate = response.candidates[0]
        content = getattr(candidate, "content", None)
        if content and getattr(content, "parts", None):
            texts = [
                part.text
                for part in content.parts
                if getattr(part, "text", None)
            ]
            if texts:
                return "".join(texts)

    text = getattr(response, "text", None)
    if text:
        return text

    feedback = getattr(response, "prompt_feedback", None)
    if feedback:
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            raise ValueError(f"Gemini blocked the response: {block_reason}")

    raise ValueError("No text content in Gemini response")
