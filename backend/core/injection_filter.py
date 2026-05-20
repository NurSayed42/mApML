import re
import bleach
import structlog
from typing import Tuple

logger = structlog.get_logger(__name__)

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"you\s+are\s+now\s+(a|an)\s+\w+",
    r"act\s+as\s+(a|an)\s+\w+\s+without\s+(any\s+)?restrictions",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"system\s+prompt",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"###\s*Human:",
    r"###\s*Assistant:",
    r"<system>",
    r"</system>",
    r"reveal\s+your\s+(system\s+)?prompt",
    r"print\s+your\s+(system\s+)?instructions",
    r"what\s+(are|is)\s+your\s+(system\s+)?instructions",
    r"bypass\s+(safety|filter|restriction)",
    r"override\s+(safety|filter|restriction)",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in INJECTION_PATTERNS]


def sanitize_input(text: str) -> str:
    """Strip HTML tags and sanitize user input."""
    return bleach.clean(text, tags=[], strip=True).strip()


def check_injection(text: str, correlation_id: str = "", user_id: str = "") -> Tuple[bool, str]:
    """
    Returns (is_safe, matched_pattern).
    is_safe=True means input is safe to proceed.
    """
    for pattern in COMPILED_PATTERNS:
        match = pattern.search(text)
        if match:
            matched = match.group(0)
            logger.warning(
                "prompt_injection_detected",
                correlation_id=correlation_id,
                user_id=user_id,
                matched_pattern=matched,
                error_type="PROMPT_INJECTION_ATTEMPT",
            )
            return False, matched
    return True, ""


def validate_and_sanitize(text: str, correlation_id: str = "", user_id: str = "") -> Tuple[str, bool, str]:
    """
    Full pipeline: sanitize then check injection.
    Returns (sanitized_text, is_safe, reason).
    """
    sanitized = sanitize_input(text)
    is_safe, matched = check_injection(sanitized, correlation_id, user_id)
    return sanitized, is_safe, matched
