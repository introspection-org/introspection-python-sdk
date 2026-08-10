"""The shared TracerProvider used by ``init()``: built once, exported once.

All spans on the shared provider flow through a single
:class:`IntrospectionSpanProcessor`, which stamps conversation/identity
baggage onto every span and exports them.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import ProxyTracerProvider

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel.types import DEFAULT_SERVICE_NAME
from introspection_sdk.utils import logger

_SENTINEL_ATTR = "_introspection_exporter_attached"
#: Where the attached processor is parked so shutdown can detach it again.
_PROCESSOR_ATTR = "_introspection_span_processor"


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
        "INTROSPECTION_SERVICE_NAME", DEFAULT_SERVICE_NAME
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

    processor = IntrospectionSpanProcessor(
        token=token, service_name=service_name, advanced=advanced
    )
    provider.add_span_processor(processor)
    setattr(provider, _SENTINEL_ATTR, True)
    setattr(provider, _PROCESSOR_ATTR, processor)


def _detach_exporter(provider: TracerProvider) -> None:
    """Remove the processor :func:`_attach_exporter` added, and its marker.

    Called by :func:`introspection_sdk.otel.shutdown`. Both halves matter:

    * The marker outliving the processor made the next :func:`init` short-
      circuit and export nothing, silently ignoring a new ``span_exporter``.
    * Leaving the shut-down processor in the provider's composite then broke
      ``force_flush`` for its replacement --
      ``SynchronousMultiSpanProcessor.force_flush`` stops at the first
      processor that returns ``False``, and a shut-down one always does.

    OpenTelemetry Python offers no public detach, so this reaches into the
    composite's processor tuple and tolerates its absence.
    """
    processor = getattr(provider, _PROCESSOR_ATTR, None)
    composite = getattr(provider, "_active_span_processor", None)
    existing = getattr(composite, "_span_processors", None)
    if composite is not None and processor is not None and existing:
        remaining = tuple(p for p in existing if p is not processor)
        if len(remaining) != len(existing):
            lock = getattr(composite, "_lock", None)
            if lock is not None:
                with lock:
                    composite._span_processors = remaining
            else:  # pragma: no cover - older SDK without the lock
                composite._span_processors = remaining
    for attr in (_SENTINEL_ATTR, _PROCESSOR_ATTR):
        if hasattr(provider, attr):
            try:
                delattr(provider, attr)
            except AttributeError:  # pragma: no cover - read-only provider
                pass
