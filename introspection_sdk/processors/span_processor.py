"""OpenTelemetry SpanProcessor for the Introspection backend."""

import os
import uuid
from urllib.parse import urljoin

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
from introspection_sdk.converters.logfire import (
    convert_logfire_to_genai,
    is_logfire_span,
)
from introspection_sdk.converters.openinference import (
    ConvertedReadableSpan,
    convert_openinference_to_genai,
    is_openinference_span,
)
from introspection_sdk.utils import logger, platform_is_emscripten
from introspection_sdk.version import VERSION

__all__ = ["IntrospectionSpanProcessor"]

_SPAN_NAME_TO_SYSTEM: tuple[tuple[str, str], ...] = (
    ("ollama", "ollama"),
    ("anthropic", "anthropic"),
    ("gemini", "google"),
    ("groq", "groq"),
    ("mistral", "mistral"),
    ("cohere", "cohere"),
    ("bedrock", "aws_bedrock"),
    ("vertexai", "google"),
    ("openai", "openai"),
)


def _infer_system_from_span_name(span_name: str | None) -> str | None:
    """Infer gen_ai.system from span name when llm.system is absent.

    Checks the lowercase span name against known provider keywords.
    """
    if not span_name:
        return None
    lower = span_name.lower()
    for keyword, system in _SPAN_NAME_TO_SYSTEM:
        if keyword in lower:
            return system
    return None


# LangChain/LangGraph internal wrapper span names to skip when walking up
# the span tree to find the actual agent/node name.
_LANGCHAIN_WRAPPER_NAMES: frozenset[str] = frozenset(
    {
        "RunnableSequence",
        "RunnableParallel",
        "RunnableMap",
        "RunnableLambda",
        "RunnableRetry",
        "_ConfigurableModel",
        "ChatOpenAI",
        "ChatAnthropic",
        "ChatGoogleGenerativeAI",
        "ChatGroq",
        # LlamaIndex low-level wrappers — the actual LLM call is the child span
        "Ollama.predict",
        "Ollama.complete",
    }
)


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

    Intercepts OpenTelemetry spans, converts OpenInference or Anthropic logfire
    formats to OTel Gen AI semantic conventions, and exports them via OTLP.

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
        ValueError: If ``INTROSPECTION_BASE_URL`` resolves to an empty string.

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
                "INTROSPECTION_BASE_URL", "https://otel.introspection.dev"
            )
            if not base_url:
                raise ValueError("INTROSPECTION_BASE_URL is not set")
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
            if base_url.endswith("/v1/traces"):
                endpoint = base_url
            else:
                endpoint = urljoin(base_url, "/v1/traces")
            logger.info(
                "Initializing introspection with endpoint: %s", endpoint
            )
            span_exporter = OTLPHTTPSpanExporter(
                endpoint=endpoint,
                compression=Compression.NoCompression,
                headers=headers,
            )

        self._service_name = service_name
        self._conversation_ids: dict[int, str] = {}
        # span_id -> (name, parent_span_id) for agent name propagation
        self._span_names: dict[int, tuple[str, int | None]] = {}

        # Store exporter for debugging
        self._span_exporter = span_exporter
        if emscripten:  # pragma: no cover
            self._span_processor = SimpleSpanProcessor(span_exporter)
        else:
            # Configure BatchSpanProcessor with shorter timeout for faster sending
            self._span_processor = BatchSpanProcessor(
                span_exporter,
                max_queue_size=2048,
                export_timeout_millis=30000,
                schedule_delay_millis=self._advanced.flush_interval_ms,
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
        if span.context:
            parent_id = span.parent.span_id if span.parent else None
            self._span_names[span.context.span_id] = (span.name, parent_id)
        self._span_processor.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span is ended.

        Detects the span format (OpenInference or Anthropic logfire) and
        converts its attributes to OTel Gen AI semantic conventions before
        forwarding to the underlying exporter.

        Args:
            span: The completed span to process.
        """
        logger.debug(
            f"Ending introspection span: {span.name} (trace_id={span.context.trace_id:x})"
        )
        if not span.context.trace_flags.sampled:
            return

        scope = span.instrumentation_scope
        scope_name = scope.name if scope else None

        extra_attrs: dict[str, int] = {}

        if is_openinference_span(scope_name):
            converted_attrs = convert_openinference_to_genai(span.attributes)
            # Inject agent name from span tree walk-up if not already present
            if converted_attrs.agent_name is None:
                parent_span_id = span.parent.span_id if span.parent else None
                agent_name = self._find_agent_name(parent_span_id)
                if agent_name:
                    converted_attrs.agent_name = agent_name
                    logger.debug(
                        f"Injected agent_name={agent_name!r} for span {span.name!r}"
                    )
            # For LLM spans, filter out raw llm./input./output.* (replaced by
            # structured gen_ai.*). For TOOL/CHAIN/etc. spans, only filter llm.*
            # so that input.value (args) and output.value (result) are preserved.
            span_kind = (span.attributes or {}).get("openinference.span.kind")
            if span_kind == "LLM":
                # Infer gen_ai.system from span name when the instrumentor
                # doesn't emit llm.system (e.g. LlamaIndex + Ollama).
                if converted_attrs.system is None:
                    converted_attrs.system = _infer_system_from_span_name(
                        span.name
                    )
                span = ConvertedReadableSpan(span, converted_attrs)
            else:
                span = ConvertedReadableSpan(
                    span, converted_attrs, filter_prefixes=("llm.",)
                )
        elif is_logfire_span(span.attributes):
            converted_attrs = convert_logfire_to_genai(span.attributes)
            span = ConvertedReadableSpan(
                span,
                converted_attrs,
                filter_prefixes=("request_data", "response_data"),
            )

        span = self._enrich_span(span, extra_override=extra_attrs or None)
        self._span_processor.on_end(span)

    def _enrich_span(
        self,
        span: ReadableSpan,
        extra_override: dict | None = None,
    ) -> ReadableSpan:
        """Add conversation ID, agent name, and service name resource to span."""
        extra: dict[str, str | int] = {}
        if extra_override:
            extra.update(extra_override)

        # Use conversation ID from baggage if set, otherwise check existing
        # attribute, then auto-generate per trace
        baggage_conv_id = otel_baggage.get_baggage("gen_ai.conversation.id")
        existing_conv_id = (span.attributes or {}).get(
            "gen_ai.conversation.id"
        )
        if baggage_conv_id:
            extra["gen_ai.conversation.id"] = str(baggage_conv_id)
        elif not existing_conv_id:
            trace_id = span.context.trace_id
            if trace_id not in self._conversation_ids:
                self._conversation_ids[trace_id] = (
                    f"intro_conv_{uuid.uuid4().hex}"
                )
            extra["gen_ai.conversation.id"] = self._conversation_ids[trace_id]

        # Propagate agent name from baggage if not already on span
        baggage_agent_name = otel_baggage.get_baggage("gen_ai.agent.name")
        if baggage_agent_name and not (span.attributes or {}).get(
            "gen_ai.agent.name"
        ):
            extra["gen_ai.agent.name"] = str(baggage_agent_name)

        # Build a new resource with service.name if provided
        resource: Resource | None = None
        if self._service_name:
            resource = span.resource.merge(
                Resource({"service.name": self._service_name})
            )

        if extra or resource is not None:
            existing = dict(span.attributes or {})
            existing.update(extra)
            span = _AttributeOverrideSpan(span, existing, resource=resource)

        return span

    def _find_agent_name(self, span_id: int | None) -> str | None:
        """Walk up the span tree to find the first non-wrapper span name.

        Skips generic LangChain wrapper names (RunnableSequence, etc.) to
        surface the actual LangGraph node name as the agent name.

        Args:
            span_id: The span_id to start walking up from.

        Returns:
            The first non-wrapper ancestor span name, or ``None`` if not found.
        """
        visited: set[int] = set()
        current_id = span_id
        while current_id is not None:
            if current_id in visited:
                break
            visited.add(current_id)
            entry = self._span_names.get(current_id)
            if entry is None:
                break
            name, parent_id = entry
            if name not in _LANGCHAIN_WRAPPER_NAMES:
                return name
            current_id = parent_id
        return None

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
