"""Testing utilities for snapshot testing."""

import json
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.id_generator import IdGenerator

ONE_SECOND_IN_NANOSECONDS = 1_000_000_000


@dataclass
class IncrementalIdGenerator(IdGenerator):
    """Generate sequentially incrementing span/trace IDs for testing."""

    trace_id_counter: int = field(default=0)
    span_id_counter: int = field(default=0)

    def generate_span_id(self) -> int:
        self.span_id_counter += 1
        return self.span_id_counter

    def generate_trace_id(self) -> int:
        self.trace_id_counter += 1
        return self.trace_id_counter


class TimeGenerator:
    """Generate incrementing timestamps (1s, 2s, 3s...) for testing."""

    def __init__(self, ns_time: int = 0) -> None:
        self.ns_time = ns_time

    def __call__(self) -> int:
        self.ns_time += ONE_SECOND_IN_NANOSECONDS
        return self.ns_time


def spans_to_dict(
    spans: tuple[ReadableSpan, ...],
    parse_json_attributes: bool = False,
    normalize_timestamps: bool = False,
) -> list[dict[str, Any]]:
    """Convert ReadableSpan objects to dicts for snapshot testing.

    Args:
        spans: Tuple of spans from InMemorySpanExporter.get_finished_spans()
        parse_json_attributes: If True, parse JSON strings in attributes
        normalize_timestamps: If True, normalize timestamps to relative values (1s, 2s, etc.)
    """

    def process_attr(value: Any) -> Any:
        if parse_json_attributes and isinstance(value, str):
            if value.startswith("{") or value.startswith("["):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
        return value

    def build_context(ctx: Any) -> dict[str, Any]:
        return {
            "trace_id": ctx.trace_id,
            "span_id": ctx.span_id,
            "is_remote": ctx.is_remote,
        }

    def build_span(span: ReadableSpan, index: int) -> dict[str, Any]:
        attrs = (
            {k: process_attr(v) for k, v in span.attributes.items()}
            if span.attributes
            else {}
        )

        if normalize_timestamps:
            # Normalize timestamps to deterministic values based on span order
            start_time = (index + 1) * ONE_SECOND_IN_NANOSECONDS
            end_time = (index + 2) * ONE_SECOND_IN_NANOSECONDS
        else:
            start_time = span.start_time
            end_time = span.end_time

        result: dict[str, Any] = {
            "name": span.name,
            "context": build_context(span.context),
            "parent": build_context(span.parent) if span.parent else None,
            "start_time": start_time,
            "end_time": end_time,
            "attributes": attrs,
        }
        if span.events:
            result["events"] = [
                {"name": e.name, "timestamp": e.timestamp} for e in span.events
            ]
        return result

    return [build_span(s, i) for i, s in enumerate(spans)]
