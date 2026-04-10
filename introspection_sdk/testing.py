"""Testing utilities for Introspection SDK."""

__all__ = ["TestSpanExporter"]

import json
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class TestSpanExporter(SpanExporter):
    """A SpanExporter that stores spans for testing assertions.

    Usage:
        exporter = TestSpanExporter()
        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(span_exporter=exporter),
        )
        # ... run code that creates spans ...
        processor.force_flush()
        spans = exporter.get_finished_spans()
        assert spans == [...]
    """

    __test__ = False  # Prevent pytest discovery

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Store spans in memory for later retrieval.

        Args:
            spans: Batch of completed spans from the span processor.

        Returns:
            Always returns ``SpanExportResult.SUCCESS``.
        """
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """No-op shutdown (in-memory exporter has nothing to clean up)."""
        pass

    def clear(self) -> None:
        """Discard all stored spans."""
        self._spans = []

    def get_finished_spans(self) -> list[dict[str, Any]]:
        """Return exported spans as dicts for snapshot assertions.

        Returns:
            List of dicts, each with ``name``, ``attributes``, ``context``,
            ``parent``, ``start_time``, and ``end_time`` keys.
        """
        return [self._span_to_dict(s) for s in self._spans]

    @staticmethod
    def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if span.attributes:
            for k, v in span.attributes.items():
                if isinstance(v, str):
                    try:
                        parsed = json.loads(v)
                        if isinstance(parsed, list | dict):
                            attrs[k] = v
                            continue
                    except (json.JSONDecodeError, ValueError):
                        pass
                attrs[k] = v

        result: dict[str, Any] = {
            "name": span.name,
            "attributes": attrs,
        }
        if span.context:
            result["context"] = {
                "trace_id": span.context.trace_id,
                "span_id": span.context.span_id,
            }
        if span.parent:
            result["parent"] = {
                "trace_id": span.parent.trace_id,
                "span_id": span.parent.span_id,
            }
        if span.start_time:
            result["start_time"] = span.start_time
        if span.end_time:
            result["end_time"] = span.end_time
        return result
