"""The shared TracerProvider used by ``init()``: built once, exported once.

All spans on the shared provider flow through a single
:class:`IntrospectionSpanProcessor`, which converts OpenInference/Logfire spans
to gen_ai semconv, stamps conversation/identity baggage onto every span
(including native Gemini/Anthropic spans), and exports them.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import ProxyTracerProvider

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.utils import logger

_SENTINEL_ATTR = "_introspection_exporter_attached"


def _get_or_create_tracer_provider(
    *,
    token: str | None,
    explicit_provider: TracerProvider | None,
    advanced: AdvancedOptions,
    service_name: str | None = None,
) -> TracerProvider:
    """Return the provider ``init()`` should use, attaching our pipeline to it.

    Precedence: an explicit provider is used untouched; an existing global
    provider gets our span processor attached; otherwise a new one is created
    and set as the global.
    """
    if explicit_provider is not None:
        return explicit_provider

    current = trace.get_tracer_provider()
    if not isinstance(current, ProxyTracerProvider):
        if hasattr(current, "add_span_processor"):
            _attach_exporter(current, token, advanced, service_name)  # type: ignore[arg-type]
        else:
            logger.warning(
                "Existing TracerProvider %r does not support "
                "add_span_processor; Introspection spans will not be exported.",
                type(current).__name__,
            )
        return current  # type: ignore[return-value]

    resolved_service = service_name or os.getenv(
        "INTROSPECTION_SERVICE_NAME", "introspection"
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": resolved_service}),
        id_generator=advanced.id_generator,
    )
    _attach_exporter(provider, token, advanced, resolved_service)
    trace.set_tracer_provider(provider)
    return provider


def _attach_exporter(
    provider: TracerProvider,
    token: str | None,
    advanced: AdvancedOptions,
    service_name: str | None = None,
) -> None:
    """Attach the enriching IntrospectionSpanProcessor to ``provider``, once.

    A no-op if already attached, or if there is neither a custom exporter nor a
    token to authenticate with.
    """
    if getattr(provider, _SENTINEL_ATTR, False):
        return

    if advanced.span_exporter is None and not (
        token or os.getenv("INTROSPECTION_TOKEN")
    ):
        logger.warning(
            "No INTROSPECTION_TOKEN set; spans will not be exported."
        )
        return

    from introspection_sdk.otel.processors.span_processor import (
        IntrospectionSpanProcessor,
    )

    provider.add_span_processor(
        IntrospectionSpanProcessor(
            token=token, service_name=service_name, advanced=advanced
        )
    )
    setattr(provider, _SENTINEL_ATTR, True)
