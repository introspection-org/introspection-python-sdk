"""Shared construction helpers for OpenTelemetry batch processors."""

from __future__ import annotations


def batch_processor_options(
    *,
    max_queue_size: int | None,
    max_batch_size: int | None,
    flush_interval_ms: int | None,
    export_timeout_ms: int | None,
) -> dict[str, int]:
    """Return only explicitly configured batch processor options.

    Omitting an option lets the installed OpenTelemetry SDK choose its
    default, including any environment-variable override it supports.
    """
    options: dict[str, int] = {}
    if max_queue_size is not None:
        options["max_queue_size"] = max_queue_size
    if max_batch_size is not None:
        options["max_export_batch_size"] = max_batch_size
    if flush_interval_ms is not None:
        options["schedule_delay_millis"] = flush_interval_ms
    if export_timeout_ms is not None:
        options["export_timeout_millis"] = export_timeout_ms
    return options
