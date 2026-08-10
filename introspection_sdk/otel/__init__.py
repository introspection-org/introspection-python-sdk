"""OpenTelemetry surface for the Introspection SDK.

Requires the ``[otel]`` install extra::

    pip install introspection-sdk[otel]

Exports the independent telemetry surfaces:

* :class:`IntrospectionLogs` — OTLP logs emitter for
  ``track`` / ``feedback`` / ``identify``.
* :class:`IntrospectionSpanProcessor` —
  span/trace processors that forward to the Introspection backend.

Also exposes the one-liner ``init()`` entry point, which wires both surfaces
onto a shared :class:`~opentelemetry.sdk.trace.TracerProvider`, plus the
context managers that scope conversation / agent / identity baggage onto
everything emitted inside them.
"""

from __future__ import annotations

import atexit
from dataclasses import replace
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel._conversation import (
    conversation,
    new_conversation_id,
)
from introspection_sdk.otel._provider import (
    _detach_exporter,
    _get_or_create_tracer_provider,
)
from introspection_sdk.otel.logs import IntrospectionLogs
from introspection_sdk.otel.processors.span_processor import (
    IntrospectionSpanProcessor,
)
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
    "Attr",
    "Baggage",
    "EventName",
    "FeedbackProperties",
    "init",
    "shutdown",
    "get_client",
    "get_tracer_provider",
    "conversation",
    "new_conversation_id",
    "track",
    "feedback",
    "identify",
    "with_agent",
    "with_conversation",
    "with_user_id",
    "with_anonymous_id",
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
    advanced: AdvancedOptions | None = None,
) -> TracerProvider:
    """Build (or adopt) the shared provider and start the analytics stream.

    Idempotent: repeated calls return the already-configured provider.

    Args:
        token: Auth token. Falls back to ``INTROSPECTION_TOKEN``.
        service_name: Service name for spans *and* events. Falls back to
            ``INTROSPECTION_SERVICE_NAME``, then
            :data:`~introspection_sdk.otel.types.DEFAULT_SERVICE_NAME`.
        base_url: API base URL. Falls back to ``INTROSPECTION_BASE_OTEL_URL``.
        tracer_provider: Use this provider instead of creating/finding one.
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

    # The OTel ``track`` / ``feedback`` / ``identify`` surface lives on
    # IntrospectionLogs (logs are a separate OTLP stream from spans).
    client = IntrospectionLogs(
        token=token,
        service_name=service_name,
        # resolved_advanced, not the bare parameter: a caller who configured
        # only `advanced.base_url` would otherwise point spans at their
        # collector while logs still went to the default production endpoint.
        base_otel_url=resolved_advanced.base_url,
        additional_headers=resolved_advanced.additional_headers,
        log_exporter=resolved_advanced.log_exporter,
        flush_interval_ms=resolved_advanced.flush_interval_ms,
        max_batch_size=resolved_advanced.max_batch_size,
        max_queue_size=resolved_advanced.max_queue_size,
        export_timeout_ms=resolved_advanced.export_timeout_ms,
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


def shutdown() -> None:
    """Flush and tear down the telemetry configured by :func:`init`.

    Clears the module state and the provider's "already attached" marker, so
    a later :func:`init` builds a fresh logs client and attaches a fresh span
    processor. Without clearing the marker the second :func:`init` found the
    same global provider, short-circuited, and silently exported nothing --
    including ignoring a new ``advanced.span_exporter``.

    Note the *provider* itself is reused: OpenTelemetry Python refuses to
    replace an already-set global ``TracerProvider``, so a re-``init`` can
    only reconfigure the one that is there.

    Registered as an ``atexit`` hook by :func:`init`; call it directly when
    you need the flush to happen at a known point.
    """
    provider = _state["provider"]
    _shutdown()
    if provider is not None:
        _detach_exporter(provider)
    _state["provider"] = None
    _state["client"] = None


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
    provider = _state["provider"]
    if provider is not None:
        _detach_exporter(provider)
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
) -> None:
    """Proxy to the global IntrospectionLogs.identify(). Requires init() first."""
    get_client().identify(
        user_id,
        traits=traits,
        anonymous_id=anonymous_id,
        event_id=event_id,
    )


# The baggage-scoping context managers below set the same baggage keys the
# span processor reads, so scoping with these stamps both the events and
# every span emitted inside the block.


def with_agent(agent_name: str, agent_id: str | None = None) -> Any:
    """Proxy to the global IntrospectionLogs.set_agent() context manager."""
    return get_client().set_agent(agent_name, agent_id=agent_id)


def with_conversation(
    conversation_id: str | None = None,
    previous_response_id: str | None = None,
) -> Any:
    """Proxy to the global IntrospectionLogs.set_conversation() manager."""
    return get_client().set_conversation(
        conversation_id=conversation_id,
        previous_response_id=previous_response_id,
    )


def with_user_id(user_id: str) -> Any:
    """Proxy to the global IntrospectionLogs.set_user_id() context manager."""
    return get_client().set_user_id(user_id)


def with_anonymous_id(anonymous_id: str) -> Any:
    """Proxy to the global IntrospectionLogs.set_anonymous_id() manager."""
    return get_client().set_anonymous_id(anonymous_id)
