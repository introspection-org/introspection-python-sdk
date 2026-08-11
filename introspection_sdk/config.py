"""Configuration options for Introspection SDK."""

__all__ = ["AdvancedOptions"]

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator

if TYPE_CHECKING:
    from opentelemetry.sdk._logs.export import LogRecordExporter


@dataclass
class AdvancedOptions:
    """Advanced options for configuration and testing.

    These options customize the OTLP endpoint, headers, and batching, and let
    tests inject in-memory exporters. They configure telemetry only —
    :class:`~introspection_sdk.IntrospectionClient` takes no ``advanced``
    argument.

    Example:
        ```python
        from introspection_sdk import IntrospectionSpanProcessor
        from introspection_sdk.config import AdvancedOptions
        from introspection_sdk.testing import TestSpanExporter

        # Custom collector and headers
        processor = IntrospectionSpanProcessor(
            token="your-token",
            advanced=AdvancedOptions(
                base_url="http://localhost:5418",
                additional_headers={"X-Custom-Header": "value"},
                flush_interval_ms=1000,
                max_batch_size=50,
            ),
        )

        # Testing with an in-memory exporter
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(
                span_exporter=TestSpanExporter(),
            ),
        )
        ```
    """

    base_url: str | None = None
    """Base URL for the API.

    If not provided, uses INTROSPECTION_BASE_OTEL_URL env var or default.
    """

    additional_headers: dict[str, str] | None = None
    """Additional HTTP headers to include in requests."""

    span_exporter: SpanExporter | None = None
    """Custom span exporter. If provided, bypasses the default OTLP exporter.
    Use TestSpanExporter for testing."""

    log_exporter: "LogRecordExporter | None" = None
    """Custom log exporter. If provided, bypasses the default OTLP exporter.
    Use for testing or custom export logic."""

    flush_interval_ms: int | None = None
    """Flush interval in milliseconds for batch processors (spans and logs).

    ``None`` leaves the OpenTelemetry processor default unchanged.
    """

    max_batch_size: int | None = None
    """Maximum batch size before auto-flush (spans and logs).

    ``None`` leaves the OpenTelemetry processor default unchanged. Set to
    ``1`` only when the caller explicitly wants immediate one-span export.
    """

    max_queue_size: int | None = None
    """Maximum queued telemetry records before export.

    ``None`` leaves the OpenTelemetry processor default unchanged.
    """

    message_flush_debounce_ms: int | None = None
    """How long to wait after the last conversation span ends before flushing
    it, in milliseconds. ``None`` uses 250; ``0`` disables the eager flush and
    exports on :attr:`flush_interval_ms` alone.

    Spans are emitted on span *end*, so a logged message is exportable the
    moment it completes -- but the batch processor would still sit on it for
    the flush interval. This shortens that wait so a message reaches the
    platform (and any live view of it) about as fast as it was produced.

    It is a debounce rather than a flush-per-span so a turn's spans still
    export together: single-span batches are wasteful on the wire, and the
    ingest processor deduplicates provider spans that share a
    ``gen_ai.response.id`` within one batch, which it can only do when they
    arrive together. A continuous span stream can keep resetting the debounce,
    so the flush is capped at :attr:`flush_interval_ms` after the first pending
    span -- this option only ever makes an export sooner, never later.
    """

    export_timeout_ms: int | None = None
    """Maximum time allowed for a batch export, in milliseconds.

    ``None`` leaves the OpenTelemetry processor default unchanged.
    """

    id_generator: IdGenerator = field(default_factory=RandomIdGenerator)
    """Generator for trace and span IDs, used when ``init()`` creates the
    provider. Use ``IncrementalIdGenerator`` for deterministic testing."""
