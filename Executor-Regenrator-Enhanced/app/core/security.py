"""
Security Module - Production Grade

Features:
- API Key Authentication
- Rate Limiting
- Request Validation
- Sandbox Execution Guards
"""

import time
import hashlib
import secrets
import logging
from typing import Optional, Dict, Callable, Any
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
import asyncio

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

logger = logging.getLogger("security")


# ==================================================
# API Key Authentication
# ==================================================

class APIKeyValidator:
    """
    Validates API keys with constant-time comparison
    to prevent timing attacks.
    """
    
    def __init__(self):
        self.settings = get_settings()
    
    def validate(self, api_key: Optional[str]) -> bool:
        """
        Validate an API key using constant-time comparison.
        """
        if not api_key:
            return False
        
        settings = get_settings()
        # Check against secret key
        if settings.API_SECRET_KEY:
            if secrets.compare_digest(
                api_key.encode("utf-8"),
                settings.API_SECRET_KEY.encode("utf-8")
            ):
                return True
        
        # Check against allowed keys list
        for allowed_key in settings.ALLOWED_API_KEYS:
            if secrets.compare_digest(
                api_key.encode("utf-8"),
                allowed_key.encode("utf-8")
            ):
                return True
        
        return False
    
    def hash_key(self, api_key: str) -> str:
        """
        Create a safe hash of an API key for logging.
        """
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for API key authentication.
    """
    
    # Paths that don't require authentication
    PUBLIC_PATHS = {"/health", "/health/live", "/health/ready", "/metrics", "/docs", "/openapi.json"}
    
    def __init__(self, app, validator: Optional[APIKeyValidator] = None):
        super().__init__(app)
        self.validator = validator or APIKeyValidator()
        self.settings = get_settings()
    
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        # Skip auth for public paths
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)
        
        # Skip if auth is disabled
        if not settings.ENABLE_API_AUTH:
            return await call_next(request)
        
        # Extract API key from header
        api_key = request.headers.get(settings.API_KEY_HEADER)
        
        if not api_key:
            logger.warning(
                "AUTH_MISSING | path=%s | client=%s",
                request.url.path,
                request.client.host if request.client else "unknown"
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "API key required"},
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        if not self.validator.validate(api_key):
            logger.warning(
                "AUTH_INVALID | path=%s | client=%s | key_hash=%s",
                request.url.path,
                request.client.host if request.client else "unknown",
                self.validator.hash_key(api_key)
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid API key"},
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        # Store validated key hash in request state
        request.state.api_key_hash = self.validator.hash_key(api_key)
        
        return await call_next(request)


# ==================================================
# Rate Limiting
# ==================================================

@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_update: float
    
    def __init__(self, capacity: int):
        self.tokens = float(capacity)
        self.last_update = time.time()


class RateLimiter:
    """
    Token bucket rate limiter with sliding window.
    
    Features:
    - Per-client rate limiting
    - Configurable burst size
    - Automatic cleanup of stale buckets
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        cleanup_interval: int = 300,
    ):
        self.rate = requests_per_minute / 60.0  # tokens per second
        self.capacity = burst_size
        self.buckets: Dict[str, RateLimitBucket] = {}
        self.cleanup_interval = cleanup_interval
        self.last_cleanup = time.time()
        self._lock = asyncio.Lock()
    
    def _get_client_key(self, request: Request) -> str:
        """
        Get a unique key for the client.
        Uses API key hash if available, falls back to IP.
        """
        # Prefer API key hash for authenticated requests
        if hasattr(request.state, "api_key_hash"):
            return f"key:{request.state.api_key_hash}"
        
        # Fall back to IP address
        settings = get_settings()
        if settings.TRUST_FORWARDED_IP:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return f"ip:{forwarded.split(',')[0].strip()}"
        
        if request.client:
            return f"ip:{request.client.host}"
        
        return "ip:unknown"
    
    async def is_allowed(self, request: Request) -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.
        
        Returns:
            Tuple of (allowed: bool, info: dict with limit info)
        """
        client_key = self._get_client_key(request)
        now = time.time()
        
        async with self._lock:
            # Periodic cleanup
            if now - self.last_cleanup > self.cleanup_interval:
                await self._cleanup_stale_buckets(now)
                self.last_cleanup = now
            
            # Get or create bucket
            if client_key not in self.buckets:
                self.buckets[client_key] = RateLimitBucket(self.capacity)
            
            bucket = self.buckets[client_key]
            
            # Refill tokens based on time elapsed
            elapsed = now - bucket.last_update
            bucket.tokens = min(
                self.capacity,
                bucket.tokens + elapsed * self.rate
            )
            bucket.last_update = now
            
            # Check if request is allowed
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, {
                    "limit": self.capacity,
                    "remaining": int(bucket.tokens),
                    "reset": int(now + (self.capacity - bucket.tokens) / self.rate),
                }
            
            # Calculate retry-after
            retry_after = int((1 - bucket.tokens) / self.rate) + 1
            
            return False, {
                "limit": self.capacity,
                "remaining": 0,
                "reset": int(now + retry_after),
                "retry_after": retry_after,
            }
    
    async def _cleanup_stale_buckets(self, now: float):
        """Remove buckets that haven't been used recently."""
        stale_threshold = now - self.cleanup_interval
        stale_keys = [
            key for key, bucket in self.buckets.items()
            if bucket.last_update < stale_threshold
        ]
        for key in stale_keys:
            del self.buckets[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.
    """
    
    # Paths exempt from rate limiting
    EXEMPT_PATHS = {"/health", "/health/live", "/health/ready", "/metrics"}
    
    def __init__(self, app, limiter: Optional[RateLimiter] = None):
        super().__init__(app)
        settings = get_settings()
        self.limiter = limiter or RateLimiter(
            requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
            burst_size=settings.RATE_LIMIT_BURST_SIZE,
        )
        self.enabled = settings.ENABLE_RATE_LIMITING
    
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        # Skip if disabled or exempt path
        if not settings.ENABLE_RATE_LIMITING or request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)
        
        allowed, info = await self.limiter.is_allowed(request)
        
        if not allowed:
            logger.warning(
                "RATE_LIMIT_EXCEEDED | path=%s | client=%s",
                request.url.path,
                request.client.host if request.client else "unknown"
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": info.get("retry_after", 60),
                },
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset"]),
                    "Retry-After": str(info.get("retry_after", 60)),
                }
            )
        
        response = await call_next(request)
        
        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(info["reset"])
        
        return response


# ==================================================
# Sandbox Execution Guard
# ==================================================

class SandboxGuard:
    """
    Guards for sandboxed Python execution.
    
    Validates scripts before execution to prevent:
    - System access
    - Network access
    - File system manipulation outside sandbox
    - Process spawning
    """
    
    # Dangerous imports
    FORBIDDEN_IMPORTS = {
        "subprocess", "shutil", "socket",
        "pickle", "marshal", "ctypes", "multiprocessing",
        "signal", "resource", "pty", "tty",
        "fcntl", "termios", "select", "mmap", "syslog",
        "commands", "popen2", "posix", "posixpath",
    }
    
    # Dangerous builtins
    FORBIDDEN_BUILTINS = {
        "eval", "exec", "compile", "__import__",
        "file", "input", "raw_input",
    }
    
    # Dangerous patterns
    FORBIDDEN_PATTERNS = [
        r"__builtins__",
        r"__import__",
        r"globals\s*\(",
        r"locals\s*\(",
        r"getattr\s*\(",
        r"setattr\s*\(",
        r"delattr\s*\(",
        r"hasattr\s*\(.*,\s*['\"]__",
        r"os\s*\.\s*system",
        r"os\s*\.\s*popen",
        r"os\s*\.\s*spawn",
        r"subprocess\s*\.",
        r"shutil\s*\.",
        r"socket\s*\.",
    ]
    
    def __init__(self):
        import re
        from app.executors.sandbox import ScriptSecurityValidator
        self._patterns = [re.compile(p) for p in self.FORBIDDEN_PATTERNS]
        self._validator = ScriptSecurityValidator(strict_mode=True)
    
    def validate_script(self, script_content: str) -> tuple[bool, Optional[str]]:
        """
        Validate a script for sandbox safety.
        
        Returns:
            Tuple of (is_safe: bool, reason: Optional[str])
        """
        is_safe, reason = self._validator.validate(script_content)
        if not is_safe:
            return False, reason

        import ast
        
        # Check for forbidden patterns
        for pattern in self._patterns:
            if pattern.search(script_content):
                return False, f"Forbidden pattern detected: {pattern.pattern}"
        
        # Parse and analyze AST
        try:
            tree = ast.parse(script_content)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"
        
        # Check imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name in self.FORBIDDEN_IMPORTS:
                        return False, f"Forbidden import: {module_name}"
            
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if module_name in self.FORBIDDEN_IMPORTS:
                        return False, f"Forbidden import: {module_name}"
            
            # Check for dangerous calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_BUILTINS:
                        return False, f"Forbidden builtin: {node.func.id}"
        
        return True, None
    
    def create_restricted_globals(self) -> dict:
        """
        Create a restricted globals dictionary for exec().
        """
        import builtins
        
        safe_builtins = {
            name: getattr(builtins, name)
            for name in dir(builtins)
            if name not in self.FORBIDDEN_BUILTINS
            and not name.startswith("_")
        }
        
        return {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
            "__doc__": None,
        }


# ==================================================
# Request Validation
# ==================================================

class RequestValidator:
    """
    Validates incoming requests for security.
    """
    
    # Suspicious headers
    SUSPICIOUS_HEADERS = {
        "X-Forwarded-Host",
        "X-Original-URL",
        "X-Rewrite-URL",
    }
    
    def validate(self, request: Request) -> tuple[bool, Optional[str]]:
        """
        Validate a request for security issues.
        
        Returns:
            Tuple of (is_valid: bool, reason: Optional[str])
        """
        # Check for suspicious headers (potential header injection)
        for header in self.SUSPICIOUS_HEADERS:
            if header.lower() in [h.lower() for h in request.headers.keys()]:
                return False, f"Suspicious header: {header}"
        
        # Check for path traversal attempts
        path = request.url.path
        if ".." in path or "//" in path:
            return False, "Path traversal attempt detected"
        
        # Check for null bytes
        if "\x00" in path:
            return False, "Null byte in path"
        
        return True, None


# ==================================================
# Dependency Injection Helpers
# ==================================================

def require_api_key(request: Request) -> str:
    """
    FastAPI dependency to require API key authentication.
    """
    settings = get_settings()
    
    if not settings.ENABLE_API_AUTH:
        return "auth_disabled"
    
    api_key = request.headers.get(settings.API_KEY_HEADER)
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    validator = APIKeyValidator()
    if not validator.validate(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    return validator.hash_key(api_key)


# ==================================================
# Decorators
# ==================================================

def rate_limit(requests_per_minute: int = 60):
    """
    Decorator for rate limiting specific endpoints.
    """
    limiter = RateLimiter(requests_per_minute=requests_per_minute)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")
            
            if request:
                allowed, info = await limiter.is_allowed(request)
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded",
                        headers={"Retry-After": str(info.get("retry_after", 60))}
                    )
            
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator
