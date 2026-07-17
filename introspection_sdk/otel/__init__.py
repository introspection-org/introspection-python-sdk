"""OpenTelemetry surface for the Introspection SDK.

Requires the ``[otel]`` install extra::

    pip install introspection-sdk[otel]

Provides independent OTLP log and trace export.
"""

from __future__ import annotations

import atexit
from dataclasses import replace
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel.anthropic import (
    REDACTED_THINKING_CONTENT,
    AnthropicInstrumentor,
)
from introspection_sdk.otel.conversation import conversation
from introspection_sdk.otel.gemini import GeminiInstrumentor
from introspection_sdk.otel.integrations import (
    discover_integrations,
    setup_integrations,
)
from introspection_sdk.otel.integrations._provider import (
    _get_or_create_tracer_provider,
)
from introspection_sdk.otel.integrations.base import DidNotEnable, Integration
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
from introspection_sdk.otel.sessions import IntrospectionConversationsSession
from introspection_sdk.otel.types import (
    Attr,
    Baggage,
    EventName,
    FeedbackProperties,
)
from introspection_sdk.utils import logger

__all__ = [
    "IntrospectionLogs",
    "IntrospectionSpanProcessor",
    "IntrospectionTracingProcessor",
    "ClaudeTracingProcessor",
    "IntrospectionCallbackHandler",
    "AnthropicInstrumentor",
    "GeminiInstrumentor",
    "IntrospectionConversationsSession",
    "Attr",
    "Baggage",
    "EventName",
    "FeedbackProperties",
    "REDACTED_THINKING_CONTENT",
    "init",
    "get_client",
    "get_tracer_provider",
    "conversation",
    "Integration",
    "DidNotEnable",
    "track",
    "feedback",
    "identify",
]

_state: dict[str, Any] = {
    "provider": None,
    "client": None,
    "atexit_registered": False,
}


def init(
    token: str | None = None,
    *,
    service_name: str | None = None,
    base_url: str | None = None,
    tracer_provider: TracerProvider | None = None,
    integrations: list[type[Integration]] | None = None,
    auto_discover: bool = True,
    advanced: AdvancedOptions | None = None,
) -> TracerProvider:
    """Configure the optional OTLP telemetry provider and logs client.

    Idempotent: repeated calls return the already-configured provider without
    reconfiguring telemetry.

    Args:
        token: Auth token. Falls back to ``INTROSPECTION_TOKEN``.
        service_name: Service name for spans. Falls back to
            ``INTROSPECTION_SERVICE_NAME``, then ``"introspection"``.
        base_url: API base URL. Falls back to ``INTROSPECTION_BASE_OTEL_URL``.
        tracer_provider: Use this provider instead of creating/finding one.
        integrations: Experimental compatibility overrides.
        auto_discover: Enable experimental compatibility discovery.
        advanced: Advanced configuration (custom exporter, headers, etc.).
    """
    if _state["provider"] is not None:
        logger.debug("introspection.init() already called; returning provider")
        return _state["provider"]

    resolved_advanced = advanced or AdvancedOptions()
    if base_url is not None and resolved_advanced.base_url is None:
        resolved_advanced = replace(resolved_advanced, base_url=base_url)

    provider = _get_or_create_tracer_provider(
        token=token,
        explicit_provider=tracer_provider,
        advanced=resolved_advanced,
        service_name=service_name,
    )

    to_install: list[type[Integration]] = []
    if auto_discover:
        to_install.extend(discover_integrations())
    if integrations:
        to_install.extend(integrations)
    setup_integrations(to_install, tracer_provider=provider)

    # The OTel ``track`` / ``feedback`` / ``identify`` surface lives on
    # IntrospectionLogs (logs are a separate OTLP stream from spans).
    client = IntrospectionLogs(
        token=token,
        service_name=service_name,
        base_otel_url=base_url,
        log_exporter=resolved_advanced.log_exporter,
        flush_interval_ms=resolved_advanced.flush_interval_ms,
        max_batch_size=resolved_advanced.max_batch_size or 100,
    )

    _state["provider"] = provider
    _state["client"] = client
    if not _state["atexit_registered"]:
        atexit.register(_shutdown)
        _state["atexit_registered"] = True
    return provider


def get_client() -> IntrospectionLogs:
    """Return the global logs client. Raises if ``init()`` has not been called."""
    client = _state["client"]
    if client is None:
        raise RuntimeError(
            "introspection.init() must be called before using "
            "feedback/track/identify."
        )
    return client


def get_tracer_provider() -> TracerProvider:
    """Return the shared provider. Raises if ``init()`` has not been called."""
    provider = _state["provider"]
    if provider is None:
        raise RuntimeError("introspection.init() must be called first.")
    return provider


def _shutdown() -> None:
    client = _state["client"]
    if client is not None:
        try:
            client.shutdown()
        except Exception as e:
            logger.debug("Error shutting down client: %s", e)
    provider = _state["provider"]
    if provider is not None and hasattr(provider, "shutdown"):
        try:
            provider.shutdown()
        except Exception as e:
            logger.debug("Error shutting down provider: %s", e)


def _reset_for_tests() -> None:
    # atexit registrations can't be cleanly removed, so leave that flag set.
    _state["provider"] = None
    _state["client"] = None


def track(
    event_name: str,
    properties: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Proxy to the global IntrospectionLogs.track(). Requires init() first."""
    get_client().track(event_name, properties, **kwargs)


def feedback(name: str, **kwargs: Any) -> None:
    """Proxy to the global IntrospectionLogs.feedback(). Requires init() first."""
    get_client().feedback(name, **kwargs)


def identify(
    user_id: str,
    traits: dict[str, Any] | None = None,
    anonymous_id: str | None = None,
    event_id: str | None = None,
) -> Any:
    """Proxy to the global IntrospectionLogs.identify() context manager."""
    return get_client().identify(
        user_id,
        traits=traits,
        anonymous_id=anonymous_id,
        event_id=event_id,
    )
