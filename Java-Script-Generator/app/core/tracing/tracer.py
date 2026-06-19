# app/core/tracing/tracer.py
"""
OpenTelemetry Tracer Implementation

Provides distributed tracing with support for:
- OTLP export (Jaeger, Zipkin, etc.)
- Automatic instrumentation
- Custom span creation
"""

import logging
from typing import Optional, Callable, Any, Dict
from functools import wraps
from contextlib import contextmanager

from app.core.config import get_settings

logger = logging.getLogger("tracing")
settings = get_settings()

# Tracing state
_tracer = None
_initialized = False


def _create_noop_tracer():
    """Create a no-op tracer when tracing is disabled."""
    class NoOpSpan:
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            pass
        
        def set_attribute(self, key: str, value: Any):
            pass
        
        def set_status(self, status):
            pass
        
        def record_exception(self, exc: Exception):
            pass
        
        def add_event(self, name: str, attributes: dict = None):
            pass
    
    class NoOpTracer:
        def start_as_current_span(self, name: str, **kwargs):
            return NoOpSpan()
        
        def start_span(self, name: str, **kwargs):
            return NoOpSpan()
    
    return NoOpTracer()


def init_tracing(
    service_name: str = None,
    endpoint: str = None,
) -> bool:
    """
    Initialize OpenTelemetry tracing.
    
    Args:
        service_name: Service name for traces
        endpoint: OTLP collector endpoint
        
    Returns:
        True if tracing initialized, False otherwise
    """
    global _tracer, _initialized
    
    if _initialized:
        return _tracer is not None
    
    if not settings.TRACING_ENABLED:
        logger.info("Tracing disabled")
        _tracer = _create_noop_tracer()
        _initialized = True
        return False
    
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        
        # Create resource
        resource = Resource(attributes={
            SERVICE_NAME: service_name or settings.APP_NAME,
        })
        
        # Create provider
        provider = TracerProvider(resource=resource)
        
        # Add OTLP exporter
        otlp_endpoint = endpoint or settings.TRACING_ENDPOINT
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            logger.info("OTLP exporter configured | endpoint=%s", otlp_endpoint)
        
        # Set global provider
        trace.set_tracer_provider(provider)
        
        # Get tracer
        _tracer = trace.get_tracer(__name__)
        _initialized = True
        
        logger.info("OpenTelemetry tracing initialized | service=%s", service_name or settings.APP_NAME)
        return True
        
    except ImportError:
        logger.warning("OpenTelemetry not installed, tracing disabled")
        _tracer = _create_noop_tracer()
        _initialized = True
        return False
    except Exception as e:
        logger.error("Failed to initialize tracing | error=%s", str(e))
        _tracer = _create_noop_tracer()
        _initialized = True
        return False


def get_tracer():
    """Get the global tracer instance."""
    global _tracer, _initialized
    
    if not _initialized:
        init_tracing()
    
    return _tracer


def trace_async(
    name: str = None,
    attributes: Dict[str, Any] = None,
):
    """
    Decorator for tracing async functions.
    
    Usage:
        @trace_async("my_operation")
        async def my_function(...):
            ...
    """
    def decorator(func: Callable):
        span_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise
        
        return wrapper
    return decorator


def trace_sync(
    name: str = None,
    attributes: Dict[str, Any] = None,
):
    """
    Decorator for tracing sync functions.
    
    Usage:
        @trace_sync("my_operation")
        def my_function(...):
            ...
    """
    def decorator(func: Callable):
        span_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise
        
        return wrapper
    return decorator


@contextmanager
def trace_span(name: str, attributes: Dict[str, Any] = None):
    """
    Context manager for creating a trace span.
    
    Usage:
        with trace_span("my_operation", {"key": "value"}):
            ...
    """
    tracer = get_tracer()
    
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        
        yield span


def add_span_attributes(attributes: Dict[str, Any]) -> None:
    """Add attributes to the current span."""
    span = get_current_span()
    if span:
        for key, value in attributes.items():
            span.set_attribute(key, value)


def record_exception(exc: Exception) -> None:
    """Record an exception on the current span."""
    span = get_current_span()
    if span:
        span.record_exception(exc)


def get_current_span():
    """Get the current active span."""
    try:
        from opentelemetry import trace
        return trace.get_current_span()
    except ImportError:
        return None

