"""Span and tracing processors for the Introspection backend."""

from introspection_sdk.otel.processors.claude_tracing_processor import (
    ClaudeTracingProcessor,
)
from introspection_sdk.otel.processors.span_processor import (
    IntrospectionSpanProcessor,
)

__all__ = [
    "ClaudeTracingProcessor",
    "IntrospectionSpanProcessor",
]
