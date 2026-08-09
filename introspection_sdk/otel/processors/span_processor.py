"""OpenTelemetry SpanProcessor for the Introspection backend."""

import os

from opentelemetry import baggage as otel_baggage
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OTLPHTTPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
)

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel._endpoint import otlp_endpoint
from introspection_sdk.otel.conversation import resolve_conversation_id
from introspection_sdk.otel.processors._batch import batch_processor_options
from introspection_sdk.otel.types import Attr, Baggage
from introspection_sdk.utils import logger, platform_is_emscripten
from introspection_sdk.version import VERSION

__all__ = ["IntrospectionSpanProcessor"]

#: A span carrying any of these is LLM-relevant and gets exported. Everything
#: else in the process (HTTP clients, web-framework routing, database drivers)
#: reaches this processor too once it is attached to the global provider, and
#: must not be shipped to Introspection.
_GEN_AI_MARKERS = (
    "gen_ai.provider.name",
    "gen_ai.operation.name",
    "gen_ai.request.model",
    "gen_ai.input.messages",
    "gen_ai.output.messages",
)

#: End-user identity baggage keys -> their semconv span-attribute keys. The
#: baggage keys use the ``identify()`` underscore form; the span attributes use
#: the dotted semconv form.
_IDENTITY_BAGGAGE_TO_ATTRIBUTE = {
    Baggage.USER_ID: Attr.USER_ID,
    Baggage.ANONYMOUS_ID: Attr.ANONYMOUS_ID,
}

#: Deprecated pre-1.27 provider key. ``gen_ai.provider.name`` supersedes it and
#: an emitter that still writes it would ship both.
_DEPRECATED_SYSTEM_KEY = "gen_ai.system"


class _AttributeOverrideSpan(ReadableSpan):
    """Minimal ReadableSpan wrapper that replaces attributes with a plain dict."""

    def __init__(
        self,
        original: ReadableSpan,
        attrs: dict,
        resource: Resource | None = None,
    ) -> None:
        self._original = original
        self._attrs = attrs
        self._resource = resource

    @property
    def attributes(self):
        return self._attrs

    def get_span_context(self):
        return self._original.get_span_context()

    @property
    def name(self) -> str:
        return self._original.name

    @property
    def context(self):
        return self._original.context

    @property
    def parent(self):
        return self._original.parent

    @property
    def resource(self):
        return (
            self._resource
            if self._resource is not None
            else self._original.resource
        )

    @property
    def instrumentation_scope(self):
        return self._original.instrumentation_scope

    @property
    def status(self):
        return self._original.status

    @property
    def start_time(self):
        return self._original.start_time

    @property
    def end_time(self):
        return self._original.end_time

    @property
    def events(self):
        return self._original.events

    @property
    def links(self):
        return self._original.links

    @property
    def dropped_attributes(self) -> int:
        return self._original.dropped_attributes

    @property
    def dropped_events(self) -> int:
        return self._original.dropped_events

    @property
    def dropped_links(self) -> int:
        return self._original.dropped_links

    def __getattr__(self, name: str):
        return getattr(self._original, name)


class IntrospectionSpanProcessor(SpanProcessor):
    """Span processor that sends traces to the Introspection API.

    Intercepts OpenTelemetry spans, drops the ones with no ``gen_ai.*`` data,
    stamps conversation / agent / identity baggage onto the rest, and exports
    them via OTLP.

    Args:
        token: Introspection API token. Falls back to the
            ``INTROSPECTION_TOKEN`` environment variable.
        service_name: Optional service name. Sets the ``service.name``
            resource attribute so it appears correctly as the service name
            in the Introspection backend.
        advanced: Optional :class:`AdvancedOptions` for custom exporters,
            headers, batch settings, etc.

    Raises:
        ValueError: If neither ``token`` nor ``INTROSPECTION_TOKEN`` is set.
        ValueError: If ``INTROSPECTION_BASE_OTEL_URL`` resolves to an empty string.

    Example::

        processor = IntrospectionSpanProcessor(token="my-token")
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(processor)
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        advanced: AdvancedOptions | None = None,
    ):
        # Use defaults if not provided
        self._advanced = advanced or AdvancedOptions()

        emscripten = platform_is_emscripten()

        if self._advanced.span_exporter:
            # Use provided exporter (for testing)
            span_exporter = self._advanced.span_exporter
        else:
            # Create default OTLP exporter
            base_url = self._advanced.base_url or os.getenv(
                "INTROSPECTION_BASE_OTEL_URL",
                "https://otel.introspection.dev",
            )
            if not base_url:
                raise ValueError("INTROSPECTION_BASE_OTEL_URL is not set")
            token = token or os.getenv("INTROSPECTION_TOKEN")
            if not token:
                raise ValueError("INTROSPECTION_TOKEN is not set")
            headers = {
                "User-Agent": f"introspection-sdk/{VERSION}",
                "Authorization": f"Bearer {token}",
                **(
                    self._advanced.additional_headers or {}
                ),  # TODO: Add validation for headers
            }
            endpoint = otlp_endpoint(base_url, "traces")
            logger.info(
                "Initializing introspection with endpoint: %s", endpoint
            )
            span_exporter = OTLPHTTPSpanExporter(
                endpoint=endpoint,
                compression=Compression.NoCompression,
                headers=headers,
            )

        self._service_name = service_name

        # Store exporter for debugging
        self._span_exporter = span_exporter
        if emscripten:  # pragma: no cover
            self._span_processor = SimpleSpanProcessor(span_exporter)
        else:
            self._span_processor = BatchSpanProcessor(
                span_exporter,
                **batch_processor_options(
                    max_queue_size=self._advanced.max_queue_size,
                    max_batch_size=self._advanced.max_batch_size,
                    flush_interval_ms=self._advanced.flush_interval_ms,
                    export_timeout_ms=self._advanced.export_timeout_ms,
                ),
            )

    def on_start(
        self, span: Span, parent_context: Context | None = None
    ) -> None:
        """Called when a span is started.

        Args:
            span: The span that was started.
            parent_context: The parent context of the span, if any.
        """
        logger.debug(
            f"Starting introspection span: {span.name} (trace_id={span.context.trace_id:x})"
        )
        self._span_processor.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span is ended.

        Drops spans with no LLM-relevant data, then stamps conversation /
        agent / identity baggage onto the rest and forwards them to the
        underlying exporter.

        Args:
            span: The completed span to process.
        """
        logger.debug(
            f"Ending introspection span: {span.name} (trace_id={span.context.trace_id:x})"
        )
        if not span.context.trace_flags.sampled:
            return

        attributes = span.attributes or {}
        if not any(attributes.get(key) is not None for key in _GEN_AI_MARKERS):
            # An infrastructure span: HTTP, routing, database. Exporting it
            # would also mint a synthetic conversation id for a span that has
            # nothing to do with a conversation.
            return

        self._span_processor.on_end(self._enrich_span(span))

    def _enrich_span(self, span: ReadableSpan) -> ReadableSpan:
        """Add conversation, agent, and identity attributes plus service name."""
        attrs = dict(span.attributes or {})
        attrs.pop(_DEPRECATED_SYSTEM_KEY, None)

        # Conversation id: baggage > existing attribute > auto-generate per
        # trace.
        baggage_conv_id = otel_baggage.get_baggage(Baggage.CONVERSATION_ID)
        if baggage_conv_id:
            attrs[Attr.CONVERSATION_ID] = str(baggage_conv_id)
        elif not attrs.get(Attr.CONVERSATION_ID):
            attrs[Attr.CONVERSATION_ID] = resolve_conversation_id(
                trace_key=str(span.context.trace_id)
            )

        # An emitter that recorded messages without naming the operation is
        # doing a chat completion.
        if not attrs.get("gen_ai.operation.name") and (
            attrs.get("gen_ai.input.messages")
            or attrs.get("gen_ai.output.messages")
        ):
            attrs["gen_ai.operation.name"] = "chat"

        # Agent name / id from baggage. Baggage wins so per-call agent
        # identity overrides any default stamped by the emitter.
        for baggage_key, attribute_key in (
            (Baggage.AGENT_NAME, Attr.AGENT_NAME),
            (Baggage.AGENT_ID, Attr.AGENT_ID),
        ):
            value = otel_baggage.get_baggage(baggage_key)
            if value:
                attrs[attribute_key] = str(value)

        # End-user identity, set once at the run root by ``identify()`` and
        # inherited by every child span through context propagation. Without
        # this, spans and the events emitted alongside them disagree about who
        # the user was.
        for (
            baggage_key,
            attribute_key,
        ) in _IDENTITY_BAGGAGE_TO_ATTRIBUTE.items():
            value = otel_baggage.get_baggage(baggage_key)
            if value:
                attrs[attribute_key] = str(value)

        # Build a new resource with service.name if provided
        resource: Resource | None = None
        if self._service_name:
            resource = span.resource.merge(
                Resource({"service.name": self._service_name})
            )

        return _AttributeOverrideSpan(span, attrs, resource=resource)

    def shutdown(self) -> None:
        """Shut down the underlying batch span processor."""
        logger.info("Shutting down introspection span processor")
        try:
            self._span_processor.shutdown()
        except Exception as e:
            logger.warning(f"Error during span processor shutdown: {e}")

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush all pending spans to the exporter.

        Args:
            timeout_millis: Maximum time in milliseconds to wait for the flush.

        Returns:
            ``True`` if the flush completed within the timeout.
        """
        logger.info("Flushing introspection span processor")
        return self._span_processor.force_flush(timeout_millis)
