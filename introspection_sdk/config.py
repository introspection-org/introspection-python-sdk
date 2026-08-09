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

    export_timeout_ms: int | None = None
    """Maximum time allowed for a batch export, in milliseconds.

    ``None`` leaves the OpenTelemetry processor default unchanged.
    """

    id_generator: IdGenerator = field(default_factory=RandomIdGenerator)
    """Generator for trace and span IDs, used when ``init()`` creates the
    provider. Use ``IncrementalIdGenerator`` for deterministic testing."""
