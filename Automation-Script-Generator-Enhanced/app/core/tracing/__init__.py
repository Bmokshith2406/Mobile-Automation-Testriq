# app/core/tracing/__init__.py
"""
OpenTelemetry Tracing System

Distributed tracing for debugging and performance monitoring.
"""

from app.core.tracing.tracer import (
    init_tracing,
    get_tracer,
    trace_async,
    trace_sync,
    add_span_attributes,
    record_exception,
    get_current_span,
)

__all__ = [
    "init_tracing",
    "get_tracer",
    "trace_async",
    "trace_sync",
    "add_span_attributes",
    "record_exception",
    "get_current_span",
]

