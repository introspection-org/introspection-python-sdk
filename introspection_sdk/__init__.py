"""Introspection Python SDK."""

from introspection_sdk.anthropic import (
    REDACTED_THINKING_CONTENT,
    AnthropicInstrumentor,
)
from introspection_sdk.client import IntrospectionClient
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.processors.claude_tracing_processor import (
    ClaudeTracingProcessor,
)
from introspection_sdk.processors.langchain_callback_handler import (
    IntrospectionCallbackHandler,
)
from introspection_sdk.processors.span_processor import (
    IntrospectionSpanProcessor,
)
from introspection_sdk.processors.tracing_processor import (
    IntrospectionTracingProcessor,
)
from introspection_sdk.types import (
    Attr,
    Baggage,
    EventName,
    FeedbackProperties,
)

__all__ = [
    "AdvancedOptions",
    "AnthropicInstrumentor",
    "REDACTED_THINKING_CONTENT",
    "Attr",
    "Baggage",
    "ClaudeTracingProcessor",
    "IntrospectionCallbackHandler",
    "EventName",
    "FeedbackProperties",
    "IntrospectionClient",
    "IntrospectionConversationsSession",
    "IntrospectionSpanProcessor",
    "IntrospectionTracingProcessor",
]


def __getattr__(name: str) -> object:
    if name == "IntrospectionConversationsSession":
        from introspection_sdk.sessions import (
            IntrospectionConversationsSession,
        )

        return IntrospectionConversationsSession
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
