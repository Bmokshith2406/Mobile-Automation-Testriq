# app/utils/sanitization.py
"""
Input Sanitization Utilities

Protects against prompt injection and ensures safe filesystem operations.
"""

import logging
import re
import hashlib
from typing import Optional

logger = logging.getLogger("sanitization")

# Patterns that could indicate prompt injection attempts
DANGEROUS_PROMPT_PATTERNS = [
    r"```",                          # Code fence escape
    r"IGNORE\s+(PREVIOUS|ALL|ABOVE)",  # Instruction override
    r"SYSTEM\s*:",                   # System prompt injection
    r"USER\s*:",                     # User prompt injection
    r"ASSISTANT\s*:",                # Assistant prompt injection
    r"\[INST\]",                     # Instruction tags
    r"<\|.*?\|>",                    # Special tokens
    r"<<SYS>>",                      # System tags
    r"</s>",                         # End tokens
    r"Human:",                       # Anthropic-style
    r"Assistant:",                   # Anthropic-style
]


def sanitize_for_prompt(
    text: str,
    max_length: int = 10000,
    strict: bool = False,
) -> str:
    """
    Sanitize user input before including in LLM prompts.
    
    Args:
        text: User-provided text to sanitize
        max_length: Maximum allowed length
        strict: If True, raise ValueError on dangerous patterns
        
    Returns:
        Sanitized text safe for prompt inclusion
        
    Raises:
        ValueError: If strict=True and dangerous patterns found
    """
    if not text:
        return ""
    
    # Truncate to max length
    text = text.strip()[:max_length]
    
    # Check for dangerous patterns
    for pattern in DANGEROUS_PROMPT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            if strict:
                raise ValueError(f"Potential prompt injection detected: {pattern}")
            original_snippet = text[:80]
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
            logger.warning(
                "Prompt injection pattern redacted | pattern=%s | input_preview=%.80s",
                pattern,
                original_snippet,
            )
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove control characters (except newlines and tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    return text.strip()


def sanitize_test_case_id(test_case_id: str) -> str:
    """
    Convert test case ID into a filesystem-safe name.
    
    Args:
        test_case_id: Original test case identifier
        
    Returns:
        Filesystem-safe identifier with collision-resistant hash
        
    Raises:
        ValueError: If test_case_id is empty
    """
    if not test_case_id or not test_case_id.strip():
        raise ValueError("test_case_id cannot be empty")
    
    value = test_case_id.strip().lower()
    
    # Replace non-alphanumeric characters
    value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    
    # Truncate if too long
    if len(value) > 50:
        value = value[:50]
    
    # Add deterministic short hash for collision safety
    digest = hashlib.sha1(test_case_id.encode("utf-8")).hexdigest()[:6]
    
    return f"{value}_{digest}"


def sanitize_url(url: str) -> Optional[str]:
    """
    Validate and sanitize a URL for safe usage.
    
    Args:
        url: URL to validate
        
    Returns:
        Sanitized URL or None if invalid
    """
    if not url:
        return None
    
    url = url.strip()
    
    # Must start with http:// or https://
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return None
    
    # Remove any trailing quotes or parentheses
    url = re.sub(r'[\'")\]]+$', '', url)
    
    # Basic URL character validation
    if not re.match(r'^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+$', url):
        return None
    
    return url


def sanitize_locator_value(value: str) -> str:
    """
    Sanitize a locator value for safe usage.
    
    Args:
        value: Locator value to sanitize
        
    Returns:
        Sanitized locator value
    """
    if not value:
        return ""
    
    value = value.strip()
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    # Normalize whitespace within the value
    value = re.sub(r'\s+', ' ', value)
    
    return value

