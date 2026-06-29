"""Introspection Python SDK.

Default install ships REST-only — :class:`IntrospectionClient`
exposes ``.runtimes`` / ``.experiments`` plus the
:class:`~introspection_sdk.runner.Runner` flow for tasks and files.

Install the ``[otel]`` extra (``pip install introspection-sdk[otel]``)
to add the OpenTelemetry surface:

* :class:`IntrospectionLogs` — ``track`` / ``feedback`` / ``identify``
  emitted as OTLP log records.
* :class:`IntrospectionSpanProcessor` /
  :class:`IntrospectionTracingProcessor` /
  :class:`ClaudeTracingProcessor` — attach to your TracerProvider.
* :class:`AnthropicInstrumentor` / :class:`GeminiInstrumentor` —
  auto-instrumentation for LLM SDKs.
* :class:`IntrospectionCallbackHandler` — LangChain integration.
* :class:`IntrospectionConversationsSession` — OpenAI Agents
  conversation session helper.

The three surfaces (REST client, logs, traces) are independent —
construct only what you need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# REST-only surface — always available.
from introspection_sdk._errors import (
    AuthenticationError,
    ConflictError,
    InsufficientScopeError,
    IntrospectionAPIError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    RunnerExpiredError,
    SandboxUnavailableError,
    StreamError,
    ValidationError,
)
from introspection_sdk.auth import (
    OAuthToken,
    async_authorization_code_token,
    async_service_account_token,
    async_token_exchange,
    authorization_code_token,
    service_account_token,
    token_exchange,
)
from introspection_sdk.client import (
    AsyncIntrospectionClient,
    IntrospectionClient,
)
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.agui import (
    AGUIEvent,
    EventType,
    Interrupt,
    ResumeEntry,
)

if TYPE_CHECKING:
    # Static type-checkers see the real classes; at runtime they're
    # loaded lazily via ``__getattr__`` (see below) so the REST-only
    # install does not need ``opentelemetry`` to be importable.
    from introspection_sdk.config import AdvancedOptions
    from introspection_sdk.otel.anthropic import (
        REDACTED_THINKING_CONTENT,
        AnthropicInstrumentor,
    )
    from introspection_sdk.otel.gemini import GeminiInstrumentor
    from introspection_sdk.otel.logs import IntrospectionLogs
    from introspection_sdk.otel.processors.claude_tracing_processor import (
        ClaudeTracingProcessor,
    )
    from introspection_sdk.otel.processors.langchain_callback_handler import (
        IntrospectionCallbackHandler,
    )
    from introspection_sdk.otel.processors.span_processor import (
        IntrospectionSpanProcessor,
    )
    from introspection_sdk.otel.processors.tracing_processor import (
        IntrospectionTracingProcessor,
    )
    from introspection_sdk.otel.sessions import (
        IntrospectionConversationsSession,
    )
    from introspection_sdk.otel.types import (
        Attr,
        Baggage,
        EventName,
        FeedbackProperties,
    )

_OTEL_REQUIRED_NAMES = {
    "AdvancedOptions",
    "AnthropicInstrumentor",
    "Attr",
    "Baggage",
    "ClaudeTracingProcessor",
    "EventName",
    "FeedbackProperties",
    "GeminiInstrumentor",
    "IntrospectionCallbackHandler",
    "IntrospectionConversationsSession",
    "IntrospectionLogs",
    "IntrospectionSpanProcessor",
    "IntrospectionTracingProcessor",
    "REDACTED_THINKING_CONTENT",
}


def __getattr__(name: str) -> object:
    """Lazy-load the OTel-only symbols on first access.

    Imports are deferred so that ``import introspection_sdk`` stays
    cheap in REST-only installs. Accessing an OTel-only name without
    the ``[otel]`` extra installed raises a friendly ``ImportError``
    pointing at the install command.
    """
    if name in _OTEL_REQUIRED_NAMES:
        try:
            if name == "AdvancedOptions":
                from introspection_sdk.config import AdvancedOptions

                return AdvancedOptions
            if name == "IntrospectionLogs":
                from introspection_sdk.otel.logs import IntrospectionLogs

                return IntrospectionLogs
            if name in {
                "AnthropicInstrumentor",
                "REDACTED_THINKING_CONTENT",
            }:
                from introspection_sdk.otel.anthropic import (
                    REDACTED_THINKING_CONTENT,
                    AnthropicInstrumentor,
                )

                return {
                    "AnthropicInstrumentor": AnthropicInstrumentor,
                    "REDACTED_THINKING_CONTENT": REDACTED_THINKING_CONTENT,
                }[name]
            if name == "GeminiInstrumentor":
                from introspection_sdk.otel.gemini import (
                    GeminiInstrumentor,
                )

                return GeminiInstrumentor
            if name in {
                "Attr",
                "Baggage",
                "EventName",
                "FeedbackProperties",
            }:
                from introspection_sdk.otel.types import (
                    Attr,
                    Baggage,
                    EventName,
                    FeedbackProperties,
                )

                return {
                    "Attr": Attr,
                    "Baggage": Baggage,
                    "EventName": EventName,
                    "FeedbackProperties": FeedbackProperties,
                }[name]
            if name == "ClaudeTracingProcessor":
                from introspection_sdk.otel.processors.claude_tracing_processor import (
                    ClaudeTracingProcessor,
                )

                return ClaudeTracingProcessor
            if name == "IntrospectionCallbackHandler":
                from introspection_sdk.otel.processors.langchain_callback_handler import (
                    IntrospectionCallbackHandler,
                )

                return IntrospectionCallbackHandler
            if name == "IntrospectionSpanProcessor":
                from introspection_sdk.otel.processors.span_processor import (
                    IntrospectionSpanProcessor,
                )

                return IntrospectionSpanProcessor
            if name == "IntrospectionTracingProcessor":
                from introspection_sdk.otel.processors.tracing_processor import (
                    IntrospectionTracingProcessor,
                )

                return IntrospectionTracingProcessor
            if name == "IntrospectionConversationsSession":
                from introspection_sdk.otel.sessions import (
                    IntrospectionConversationsSession,
                )

                return IntrospectionConversationsSession
        except ImportError as exc:  # pragma: no cover - missing extra
            raise ImportError(
                f"`{name}` requires the OpenTelemetry extra. "
                "Install with `pip install introspection-sdk[otel]`."
            ) from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Always-available REST surface
    "AsyncIntrospectionClient",
    "AsyncRunner",
    "AGUIEvent",
    "AuthenticationError",
    "ConflictError",
    "EventType",
    "InsufficientScopeError",
    "IntrospectionAPIError",
    "IntrospectionClient",
    "Interrupt",
    "NetworkError",
    "NotFoundError",
    "OAuthToken",
    "RateLimitError",
    "ResumeEntry",
    "Runner",
    "RunnerExpiredError",
    "SandboxUnavailableError",
    "StreamError",
    "ValidationError",
    # Server-side OAuth helpers (machine / federated auth)
    "async_authorization_code_token",
    "async_service_account_token",
    "async_token_exchange",
    "authorization_code_token",
    "service_account_token",
    "token_exchange",
    # OTel-only (lazy-loaded; require `[otel]` extra)
    "AdvancedOptions",
    "AnthropicInstrumentor",
    "Attr",
    "Baggage",
    "ClaudeTracingProcessor",
    "EventName",
    "FeedbackProperties",
    "GeminiInstrumentor",
    "IntrospectionCallbackHandler",
    "IntrospectionConversationsSession",
    "IntrospectionLogs",
    "IntrospectionSpanProcessor",
    "IntrospectionTracingProcessor",
    "REDACTED_THINKING_CONTENT",
]
