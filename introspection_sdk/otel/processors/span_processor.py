"""OpenTelemetry SpanProcessor for the Introspection backend."""

import os
import threading
import time
import weakref

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
from introspection_sdk.otel._conversation import resolve_conversation_id
from introspection_sdk.otel._endpoint import otlp_endpoint
from introspection_sdk.otel.processors._batch import batch_processor_options
from introspection_sdk.otel.types import Attr, Baggage
from introspection_sdk.utils import logger, platform_is_emscripten
from introspection_sdk.version import USER_AGENT

__all__ = ["IntrospectionSpanProcessor"]

#: Wait after the last conversation span before flushing it, in milliseconds.
_DEFAULT_MESSAGE_FLUSH_DEBOUNCE_MS = 250

#: OpenTelemetry's own ``schedule_delay_millis`` default, which is the cap on
#: the debounce when the caller has not set ``flush_interval_ms``.
_DEFAULT_SCHEDULE_DELAY_MS = 5000

#: How long ``shutdown()`` waits for an in-flight eager flush, in seconds.
#:
#: The wait exists so the flush worker is not still inside the exporter when
#: the batch processor tears that exporter down: those spans have already left
#: the queue, so the shutdown drain cannot find them again and they would be
#: lost. The bound exists because shutdown usually runs at process exit, often
#: from ``atexit``, where a hung exporter must not hold the process open.
#: Two seconds covers an OTLP round trip with room to spare while staying far
#: below the export timeout (30s by default) that would otherwise bound the
#: wait, and it is a cap rather than a delay: the join returns the moment the
#: flush completes. If it does expire, the batch processor's own shutdown
#: still runs and drains whatever is left in the queue.
_FLUSH_JOIN_TIMEOUT_S = 2.0

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
        service_name: Optional service name (env:
            ``INTROSPECTION_SERVICE_NAME``). Sets the ``service.name``
            resource attribute so it appears correctly as the service name
            in the Introspection backend. Left unset, the provider's own
            resource is used unchanged.
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
                "User-Agent": USER_AGENT,
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

        # Left as ``None`` when nothing supplies one, so an unset option
        # leaves a provider the caller already labelled alone. Reading the
        # env var here is what makes the two streams agree: the logs surface
        # has always honoured it, so a process that set it got named events
        # and anonymous spans. JS and Rust read it in their span processors
        # for the same reason.
        self._service_name = service_name or os.getenv(
            "INTROSPECTION_SERVICE_NAME"
        )

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

        debounce_ms = self._advanced.message_flush_debounce_ms
        self._flush_debounce_ms = (
            _DEFAULT_MESSAGE_FLUSH_DEBOUNCE_MS
            if debounce_ms is None
            else max(0, debounce_ms)
        )
        self._flush_max_wait_ms = (
            self._advanced.flush_interval_ms or _DEFAULT_SCHEDULE_DELAY_MS
        )
        # Guards the two deadlines and the worker handle together: `on_end`
        # runs on whatever thread ended the span, so several can race here.
        self._flush_lock = threading.Lock()
        self._flush_due_at: float | None = None
        self._flush_hard_deadline: float | None = None
        self._flush_wake = threading.Event()
        self._flush_stop = threading.Event()
        self._flush_worker: threading.Thread | None = None
        self._flush_worker_pid = os.getpid()

        if hasattr(os, "register_at_fork"):
            # A child of `fork()` inherits no threads, so the worker handle it
            # inherits points at a thread that does not exist and nothing ever
            # starts a replacement: eager flush would be silently dead in every
            # child of a pre-forking server. The same reasoning is why the
            # OpenTelemetry batch processor registers this hook.
            #
            # Weak, so an otherwise unreachable processor is not kept alive by
            # the fork registry, which has no way to unregister.
            weak_reset = weakref.WeakMethod(self._reset_flush_state_after_fork)

            def _after_fork_in_child() -> None:
                reset = weak_reset()
                if reset is not None:
                    reset()

            os.register_at_fork(after_in_child=_after_fork_in_child)

    def _reset_flush_state_after_fork(self) -> None:
        """Rebuild the flush machinery for a freshly forked child process.

        The lock and the events are replaced rather than reused: a fork that
        landed while another thread held ``_flush_lock`` leaves the child
        holding a lock no surviving thread can release, so the first ``on_end``
        would block forever. Replacing them is safe because only one thread
        exists at this point.
        """
        self._flush_lock = threading.Lock()
        self._flush_due_at = None
        self._flush_hard_deadline = None
        self._flush_wake = threading.Event()
        self._flush_stop = threading.Event()
        self._flush_worker = None
        self._flush_worker_pid = os.getpid()

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
        # Lazy `%`-args, not an f-string: this runs on every span the
        # provider ends, and the f-string built the message -- formatting
        # the name and the 128-bit trace id -- before `logging` got the
        # chance to throw it away, which it does on any level above DEBUG.
        logger.debug(
            "Ending introspection span: %s (trace_id=%x)",
            span.name,
            span.context.trace_id,
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
        # Everything reaching here is a conversation row (the marker check
        # above rejects infrastructure spans), so this is exactly "a message
        # was logged".
        self._schedule_message_flush()

    def _schedule_message_flush(self) -> None:
        """Bring the export of a just-ended conversation span forward.

        Debounced so a turn's spans still leave together -- see
        :attr:`~introspection_sdk.config.AdvancedOptions.message_flush_debounce_ms`
        for why batching them matters downstream -- and capped at the batch
        processor's own interval so a steady span stream can't reset the timer
        indefinitely.
        """
        if self._flush_debounce_ms <= 0:
            return

        if self._flush_worker_pid != os.getpid():
            # Normally the at-fork hook has already done this. This covers the
            # child of a fork the hook did not see, and it has to happen before
            # the lock is taken, because an inherited lock may be held by a
            # thread that did not survive.
            self._reset_flush_state_after_fork()

        now = time.monotonic()
        with self._flush_lock:
            if self._flush_hard_deadline is None:
                self._flush_hard_deadline = (
                    now + self._flush_max_wait_ms / 1000
                )
            self._flush_due_at = min(
                now + self._flush_debounce_ms / 1000,
                self._flush_hard_deadline,
            )
            if self._flush_worker is None:
                # One daemon thread for the life of the processor, rather than
                # a `threading.Timer` per span: spans arrive in bursts, and
                # thread-per-span would cost more than the flush it schedules.
                # Daemon so a pending flush never holds up interpreter exit --
                # `shutdown()` is what guarantees the drain.
                self._flush_worker = threading.Thread(
                    target=self._run_flush_worker,
                    name="introspection-message-flush",
                    daemon=True,
                )
                self._flush_worker.start()
        self._flush_wake.set()

    def _run_flush_worker(self) -> None:
        """Flush once the debounce settles, re-waiting whenever it is reset."""
        while not self._flush_stop.is_set():
            with self._flush_lock:
                due = self._flush_due_at
            if due is None:
                self._flush_wake.wait()
                self._flush_wake.clear()
                continue

            remaining = due - time.monotonic()
            if remaining > 0:
                # Waking early means a newer span pushed the deadline out;
                # loop and re-read it rather than flushing on the stale one.
                if self._flush_wake.wait(remaining):
                    self._flush_wake.clear()
                continue

            with self._flush_lock:
                self._flush_due_at = None
                self._flush_hard_deadline = None
            try:
                self._span_processor.force_flush()
            except Exception as e:  # pragma: no cover - defensive
                # The batch processor still holds the span either way, so a
                # failed early flush just falls back to the scheduled one.
                logger.debug("Eager message flush failed: %s", e)

    def _cancel_message_flush(self) -> None:
        """Drop a pending eager flush -- a real flush is already happening."""
        with self._flush_lock:
            self._flush_due_at = None
            self._flush_hard_deadline = None

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
        self._cancel_message_flush()
        self._flush_stop.set()
        self._flush_wake.set()
        worker = self._flush_worker
        if worker is not None and worker is not threading.current_thread():
            # Let a flush that is already inside the exporter finish before the
            # exporter is taken away from underneath it. See
            # ``_FLUSH_JOIN_TIMEOUT_S`` for why the wait is bounded.
            worker.join(_FLUSH_JOIN_TIMEOUT_S)
            if worker.is_alive():
                logger.warning(
                    "Eager message flush still running after %ss; "
                    "shutting down anyway",
                    _FLUSH_JOIN_TIMEOUT_S,
                )
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
        self._cancel_message_flush()
        return self._span_processor.force_flush(timeout_millis)
