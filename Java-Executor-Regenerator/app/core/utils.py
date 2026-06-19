"""
Shared Utilities Module - Production Grade

Features:
- Common text extraction functions
- String manipulation utilities
- Hash utilities
- Validation helpers
"""

import re
import hashlib
import unicodedata
from typing import Optional, List, Any, TypeVar, Generic
from dataclasses import dataclass
from enum import Enum


# ==================================================
# Text Extraction Utilities
# ==================================================

def extract_quoted(text: str, quote_char: str = '"') -> Optional[str]:
    """
    Extract the first quoted string from text.
    
    Args:
        text: The text to search in
        quote_char: The quote character to use (default: ")
    
    Returns:
        The content inside quotes, or None if not found
    
    Examples:
        >>> extract_quoted('click on "Submit Button"')
        'Submit Button'
        >>> extract_quoted("type 'hello world'", quote_char="'")
        'hello world'
    """
    if not text:
        return None
    
    pattern = f'{quote_char}([^{quote_char}]*){quote_char}'
    match = re.search(pattern, text)
    if match:
        return match.group(1)
        
    if quote_char == '"':
        pattern_fallback = r"'([^']*)'"
        match_fallback = re.search(pattern_fallback, text)
        if match_fallback:
            return match_fallback.group(1)
            
    return None


def extract_all_quoted(text: str, quote_char: str = '"') -> List[str]:
    """
    Extract all quoted strings from text.
    
    Args:
        text: The text to search in
        quote_char: The quote character to use
    
    Returns:
        List of all quoted strings found
    """
    if not text:
        return []
    
    pattern = f'{quote_char}([^{quote_char}]*){quote_char}'
    return re.findall(pattern, text)


def extract_bracketed(text: str, open_char: str = "[", close_char: str = "]") -> Optional[str]:
    """
    Extract content within brackets.
    
    Args:
        text: The text to search in
        open_char: Opening bracket character
        close_char: Closing bracket character
    
    Returns:
        The content inside brackets, or None if not found
    """
    if not text:
        return None
    
    pattern = f'\\{open_char}([^\\{close_char}]+)\\{close_char}'
    match = re.search(pattern, text)
    return match.group(1) if match else None


def extract_code_block(text: str, language: Optional[str] = None) -> str:
    """
    Extract content from a markdown code block.
    
    Args:
        text: The text containing the code block
        language: Optional language specifier (e.g., 'python')
    
    Returns:
        The code content, or the original text if not found
    """
    if not text:
        return ""
    
    if language:
        pattern = f'```{language}\\s*\\n([\\s\\S]*?)\\n```'
    else:
        pattern = r'```(?:\w+)?\s*\n([\s\S]*?)\n```'
    
    match = re.search(pattern, text)
    return match.group(1).strip() if match else text


def extract_first_line(text: str) -> str:
    """
    Extract the first non-empty line from text.
    """
    if not text:
        return ""
    
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    
    return ""


# ==================================================
# String Manipulation
# ==================================================

def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text (collapse multiple spaces, trim).
    """
    if not text:
        return ""
    return " ".join(text.split())


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length with suffix.
    """
    if not text or len(text) <= max_length:
        return text or ""
    
    return text[:max_length - len(suffix)] + suffix


def slugify(text: str, separator: str = "-") -> str:
    """
    Convert text to a URL-safe slug.
    """
    if not text:
        return ""
    
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    
    # Convert to lowercase and replace spaces
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", separator, text)
    
    return text.strip(separator)


def safe_string(value: Any, default: str = "") -> str:
    """
    Safely convert a value to string.
    """
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


# ==================================================
# Hash Utilities
# ==================================================

def compute_hash(*parts: str, algorithm: str = "sha256") -> str:
    """
    Compute a hash from multiple string parts.
    
    Args:
        *parts: String parts to hash
        algorithm: Hash algorithm (sha256, md5, sha1)
    
    Returns:
        Hexadecimal hash string
    """
    h = hashlib.new(algorithm)
    for part in parts:
        if part:
            h.update(part.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def short_hash(*parts: str, length: int = 8) -> str:
    """
    Compute a short hash for identification purposes.
    """
    full_hash = compute_hash(*parts)
    return full_hash[:length]


# ==================================================
# Validation Helpers
# ==================================================

def is_valid_identifier(text: str) -> bool:
    """
    Check if text is a valid Python identifier.
    """
    if not text:
        return False
    return text.isidentifier()


def is_valid_url(text: str) -> bool:
    """
    Basic URL validation.
    """
    if not text:
        return False
    
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    
    return bool(url_pattern.match(text))


def is_valid_selector(text: str) -> bool:
    """
    Basic CSS selector validation.
    """
    if not text:
        return False
    
    # Very basic validation - check for common selector patterns
    forbidden = ["<", ">", "{", "}", "javascript:", "onclick"]
    return not any(f in text.lower() for f in forbidden)


def sanitize_selector(selector: str) -> str:
    """
    Sanitize a selector to prevent basic JavaScript injection.
    """
    if not selector:
        return ""
    
    # Remove javascript: or onload etc patterns
    sanitized = re.sub(r"javascript\s*:", "", selector, flags=re.IGNORECASE)
    return sanitized


# ==================================================
# Result Types
# ==================================================

T = TypeVar("T")


@dataclass
class Result(Generic[T]):
    """
    A result type that can represent success or failure.
    
    Usage:
        result = Result.ok(value)
        result = Result.err("error message")
        
        if result.is_ok:
            print(result.value)
        else:
            print(result.error)
    """
    _value: Optional[T] = None
    _error: Optional[str] = None
    _is_ok: bool = True
    
    @classmethod
    def ok(cls, value: T) -> "Result[T]":
        """Create a success result."""
        return cls(_value=value, _is_ok=True)
    
    @classmethod
    def err(cls, error: str) -> "Result[T]":
        """Create an error result."""
        return cls(_error=error, _is_ok=False)
    
    @property
    def is_ok(self) -> bool:
        return self._is_ok
    
    @property
    def is_err(self) -> bool:
        return not self._is_ok
    
    @property
    def value(self) -> Optional[T]:
        return self._value if self._is_ok else None
    
    @property
    def error(self) -> Optional[str]:
        return self._error if not self._is_ok else None
    
    def unwrap(self) -> T:
        """Get the value or raise an exception."""
        if self._is_ok:
            return self._value  # type: ignore
        raise ValueError(f"Result is error: {self._error}")
    
    def unwrap_or(self, default: T) -> T:
        """Get the value or return a default."""
        return self._value if self._is_ok else default


# ==================================================
# Status Enums
# ==================================================

class ExecutionStatus(str, Enum):
    """Standardized execution status values."""
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"
    RUNNING = "running"
    PENDING = "pending"

    def is_terminal(self) -> bool:
        return self in {ExecutionStatus.PASSED, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.ERROR}


class RepairOutcome(str, Enum):
    """Standardized repair outcome values."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    NOT_REPAIRABLE = "not_repairable"
    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"
    INVALID_INPUT = "invalid_input"
    VERIFICATION_FAILED = "verification_failed"

    def is_success(self) -> bool:
        return self == RepairOutcome.SUCCESS


class ActionCategory(str, Enum):
    """Categories of Playwright actions."""
    NAVIGATION = "navigation"
    INTERACTION = "interaction"
    INPUT = "input"
    ASSERTION = "assertion"
    DIALOG = "dialog"
    WAIT = "wait"


# ==================================================
# Extraction Result Types
# ==================================================

@dataclass
class ExtractionResult:
    """
    Result of an LLM extraction operation.
    
    Provides structured output with confidence and source tracking.
    """
    raw_output: str = ""
    parsed_value: Optional[Any] = None
    confidence: float = 0.0
    source: str = "llm"
    latency_ms: float = 0.0
    locator: Optional[Any] = None
    value: Optional[Any] = None
    
    @property
    def is_valid(self) -> bool:
        return self.parsed_value is not None and self.confidence > 0.5

    def is_successful(self) -> bool:
        return (self.locator is not None or self.value is not None or self.parsed_value is not None) and self.confidence > 0.5


@dataclass  
class LocatorExtractionResult:
    """Result of locator extraction."""
    strategy: Optional[str] = None
    value: Optional[str] = None
    confidence: float = 0.0
    source: str = "llm"
    
    @property
    def is_valid(self) -> bool:
        return self.strategy is not None and self.value is not None


@dataclass
class ValueExtractionResult:
    """Result of value extraction."""
    value: Optional[str] = None
    confidence: float = 0.0
    source: str = "llm"
    
    @property
    def is_valid(self) -> bool:
        return self.value is not None


# ==================================================
# Timing Utilities
# ==================================================

import time
from contextlib import contextmanager


@contextmanager
def timer():
    """
    Context manager to time a block of code.
    
    Usage:
        with timer() as t:
            do_something()
        print(f"Took {t.elapsed_ms}ms")
    """
    class Timer:
        def __init__(self):
            self.start = time.perf_counter()
            self.end: Optional[float] = None
        
        @property
        def elapsed(self) -> float:
            end = self.end or time.perf_counter()
            return end - self.start
        
        @property
        def elapsed_ms(self) -> float:
            return self.elapsed * 1000
    
    t = Timer()
    try:
        yield t
    finally:
        t.end = time.perf_counter()


class FailureFingerprint:
    @staticmethod
    def compute(*parts: str) -> str:
        h = hashlib.sha256()
        for part in parts:
            if part:
                h.update(part.encode("utf-8", errors="ignore"))
        return h.hexdigest()

    @staticmethod
    def create(step_id: str, error_type: str, error_message: str) -> str:
        return FailureFingerprint.compute(step_id, error_type, error_message)


# ==================================================
# Correlation ID Context Propagation
# ==================================================

from contextvars import ContextVar

correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Retrieve the current correlation ID from the context."""
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: Optional[str]):
    """Set the correlation ID in the current context."""
    return correlation_id_ctx.set(correlation_id)

