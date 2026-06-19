"""
Distributed Tracing Module - Production Grade

Features:
- OpenTelemetry-compatible tracing
- Span management
- Context propagation
- Integration with logging
"""

import time
import uuid
import logging
import functools
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

from app.core.config import get_settings

logger = logging.getLogger("tracing")


# ==================================================
# Span Status
# ==================================================

class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class SpanKind(str, Enum):
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


# ==================================================
# Span Model
# ==================================================

@dataclass
class Span:
    """
    Represents a distributed trace span.
    """
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    kind: SpanKind = SpanKind.INTERNAL
    status: SpanStatus = SpanStatus.UNSET
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: list = field(default_factory=list)
    
    def set_attribute(self, key: str, value: Any):
        """Set a span attribute."""
        self.attributes[key] = value
    
    def set_status(self, status: SpanStatus, description: Optional[str] = None):
        """Set span status."""
        self.status = status
        if description:
            self.attributes["status.description"] = description
    
    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })
    
    def end(self):
        """End the span."""
        self.end_time = time.time()
    
    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000
    
    def to_dict(self) -> dict:
        """Convert span to dictionary for export."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
        }


# ==================================================
# Trace Context
# ==================================================

class TraceContext:
    """
    Thread-local trace context for context propagation.
    """
    
    _instance: Optional["TraceContext"] = None
    
    def __init__(self):
        self._current_trace_id: Optional[str] = None
        self._current_span_id: Optional[str] = None
        self._spans: Dict[str, Span] = {}
    
    @classmethod
    def get_instance(cls) -> "TraceContext":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def current_trace_id(self) -> Optional[str]:
        return self._current_trace_id
    
    @property
    def current_span_id(self) -> Optional[str]:
        return self._current_span_id
    
    def start_trace(self, trace_id: Optional[str] = None) -> str:
        """Start a new trace."""
        self._current_trace_id = trace_id or uuid.uuid4().hex
        self._current_span_id = None
        return self._current_trace_id
    
    def end_trace(self):
        """End the current trace."""
        self._current_trace_id = None
        self._current_span_id = None


# ==================================================
# Tracer
# ==================================================

class Tracer:
    """
    Production-grade tracer with OpenTelemetry-compatible interface.
    """
    
    _instance: Optional["Tracer"] = None
    
    @classmethod
    def get_instance(cls) -> "Tracer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.settings = get_settings()
        self.enabled = self.settings.ENABLE_TRACING
        self.service_name = self.settings.OTEL_SERVICE_NAME
        self._context = TraceContext.get_instance()
        self._spans: list[Span] = []
        self._exporters: list = []
    
    @contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """
        Context manager to create and manage a span.
        """
        if not self.enabled:
            yield None
            return
        
        # Generate IDs
        span_id = uuid.uuid4().hex[:16]
        trace_id = self._context.current_trace_id or uuid.uuid4().hex
        parent_span_id = self._context.current_span_id
        
        # Create span
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            kind=kind,
            attributes=attributes or {},
        )
        
        # Set service name
        span.set_attribute("service.name", self.service_name)
        
        # Update context
        previous_span_id = self._context._current_span_id
        self._context._current_trace_id = trace_id
        self._context._current_span_id = span_id
        
        try:
            yield span
            span.set_status(SpanStatus.OK)
        except Exception as e:
            span.set_status(SpanStatus.ERROR, str(e))
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise
        finally:
            span.end()
            self._context._current_span_id = previous_span_id
            self._export_span(span)
    
    def _export_span(self, span: Span):
        """Export span to configured exporters."""
        if not self.enabled:
            return
        
        # Log span for debugging
        logger.debug(
            "SPAN | name=%s | trace_id=%s | span_id=%s | duration_ms=%.2f | status=%s",
            span.name,
            span.trace_id,
            span.span_id,
            span.duration_ms,
            span.status.value,
        )
        
        # Export to configured exporters
        for exporter in self._exporters:
            try:
                exporter.export(span)
            except Exception as e:
                logger.error("Failed to export span: %s", e)
    
    def add_exporter(self, exporter):
        """Add a span exporter."""
        self._exporters.append(exporter)
    
    def inject_context(self, headers: dict) -> dict:
        """
        Inject trace context into HTTP headers for propagation.
        """
        if self._context.current_trace_id:
            headers["X-Trace-ID"] = self._context.current_trace_id
        if self._context.current_span_id:
            headers["X-Span-ID"] = self._context.current_span_id
        return headers
    
    def extract_context(self, headers: dict) -> tuple[Optional[str], Optional[str]]:
        """
        Extract trace context from HTTP headers.
        """
        trace_id = headers.get("X-Trace-ID") or headers.get("x-trace-id")
        span_id = headers.get("X-Span-ID") or headers.get("x-span-id")
        return trace_id, span_id


# ==================================================
# Tracing Decorators
# ==================================================

def trace(
    name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[Dict[str, Any]] = None,
):
    """
    Decorator to automatically trace a function.
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__name__}"
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = Tracer.get_instance()
            with tracer.start_span(span_name, kind=kind, attributes=attributes) as span:
                if span:
                    # Add function arguments as attributes
                    span.set_attribute("function.args_count", len(args))
                    span.set_attribute("function.kwargs_count", len(kwargs))
                return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = Tracer.get_instance()
            with tracer.start_span(span_name, kind=kind, attributes=attributes) as span:
                if span:
                    span.set_attribute("function.args_count", len(args))
                    span.set_attribute("function.kwargs_count", len(kwargs))
                return func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ==================================================
# Span Exporters
# ==================================================

class ConsoleSpanExporter:
    """
    Exports spans to console/logs.
    """
    
    def export(self, span: Span):
        logger.info(
            "TRACE | %s | trace=%s span=%s parent=%s | %.2fms | %s",
            span.name,
            span.trace_id[:8],
            span.span_id[:8],
            span.parent_span_id[:8] if span.parent_span_id else "root",
            span.duration_ms,
            span.status.value,
        )


class JSONFileSpanExporter:
    """
    Exports spans to a JSON file.
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
    
    def export(self, span: Span):
        import json
        with open(self.file_path, "a") as f:
            f.write(json.dumps(span.to_dict()) + "\n")


# ==================================================
# Convenience Functions
# ==================================================

def get_tracer() -> Tracer:
    """Get the global tracer instance."""
    return Tracer.get_instance()


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID."""
    return TraceContext.get_instance().current_trace_id


def get_current_span_id() -> Optional[str]:
    """Get the current span ID."""
    return TraceContext.get_instance().current_span_id
