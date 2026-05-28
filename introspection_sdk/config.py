"""Configuration options for Introspection SDK."""

__all__ = ["AdvancedOptions"]

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator

if TYPE_CHECKING:
    from opentelemetry.sdk._logs.export import LogRecordExporter


@dataclass
class AdvancedOptions:
    """Advanced options for configuration and testing.

    These options allow customizing the API endpoint, headers, and injecting
    custom generators and exporters for deterministic testing.

    Example:
        ```python
        from introspection_sdk import (
            IntrospectionClient,
            IntrospectionSpanProcessor,
            IntrospectionTracingProcessor,
        )
        from introspection_sdk.config import AdvancedOptions
        from introspection_sdk.testing import TestSpanExporter

        # Custom base URL and headers for span processor
        processor = IntrospectionSpanProcessor(
            token="your-token",
            advanced=AdvancedOptions(
                base_url="http://localhost:5418/v1/traces",
                additional_headers={"X-Custom-Header": "value"},
            ),
        )

        # Testing with custom exporter
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(
                span_exporter=TestSpanExporter(),
            ),
        )

        # Custom configuration for client
        client = IntrospectionClient(
            token="your-token",
            advanced=AdvancedOptions(
                base_url="http://localhost:8080",
                flush_interval_ms=1000,
                max_batch_size=50,
                additional_headers={"X-Custom-Header": "value"},
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

    flush_interval_ms: int = 5000
    """Flush interval in milliseconds for batch processors (spans and logs).
    Lower values reduce latency but increase network requests.
    Default: 5000"""

    max_batch_size: int | None = 100
    """Maximum batch size before auto-flush.
    ``None`` uses the OTel default and opts dev/staging tokens into sequential
    export. Default: 100"""

    id_generator: IdGenerator = field(default_factory=RandomIdGenerator)
    """Generator for trace and span IDs.
    Use IncrementalIdGenerator for deterministic testing."""

    ns_timestamp_generator: Callable[[], int] = time.time_ns
    """Generator for nanosecond timestamps.
    Use TimeGenerator for deterministic testing."""
