"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.events`."""

from __future__ import annotations

import builtins
import json
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk.schemas.events import (
    KNOWN_EVENT_NAMES,
    Event,
    EventSortField,
    IntrospectionEventName,
    UnknownEvent,
)
from introspection_sdk.schemas.pagination import Paginated

# The logger of the public module, so log records keep their old name.
_logger = logging.getLogger("introspection_sdk.runner_resources.events")


#: One adapter validates a decoded row into the right union member off the
#: top-level ``event_name`` discriminator.
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class UnknownEventCounter:
    """Counts rows skipped because their family is unknown to this SDK."""

    def __init__(self) -> None:
        self.count = 0

    def increment(self, event_name: Any) -> None:
        self.count += 1
        _logger.debug(
            "skipping event row with unknown event_name %r "
            "(not in this SDK's typed family set; total skipped: %d)",
            event_name,
            self.count,
        )


#: Process-wide skip counter for unknown-family rows (observability hook).
UNKNOWN_EVENT_SKIPS = UnknownEventCounter()


EVENT_PAYLOAD_JSON_FIELDS = frozenset({"metadata", "params", "properties"})


def normalize_event_arrow_row(row: dict[str, Any]) -> dict[str, Any]:
    """Restore dict fields that the server JSON-encodes inside Arrow structs."""
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return row
    for field in EVENT_PAYLOAD_JSON_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str):
            continue
        try:
            payload[field] = json.loads(value)
        except json.JSONDecodeError:
            # Keep the original value so the typed model reports the same
            # malformed-field error instead of hiding server drift.
            pass
    return row


def validate_event_row(row: dict[str, Any]) -> Event | None:
    """Validate one wire row into the discriminated :data:`Event` union.

    Rows whose ``event_name`` falls outside the known family set are
    skipped (``None``) rather than raised — the closed set may grow
    server-side before this SDK learns the new member.
    """
    row = normalize_event_arrow_row(row)
    if row.get("event_name") not in KNOWN_EVENT_NAMES:
        UNKNOWN_EVENT_SKIPS.increment(row.get("event_name"))
        return None
    return EVENT_ADAPTER.validate_python(row)


def validate_single_event(payload: Any) -> Event | UnknownEvent:
    """Validate one wire row read by id.

    Unlike :func:`validate_event_row`, an unknown family is never skipped:
    the caller named an id, so returning nothing would be indistinguishable
    from a missing event. The envelope is validated and the payload left
    untyped instead.
    """
    row = normalize_event_arrow_row(payload)
    if row.get("event_name") not in KNOWN_EVENT_NAMES:
        UNKNOWN_EVENT_SKIPS.increment(row.get("event_name"))
        return UnknownEvent.model_validate(row)
    return EVENT_ADAPTER.validate_python(row)


def validate_event_page(payload: Any) -> Paginated[Event]:
    """Validate a JSON cursor envelope, skipping unknown-family rows."""
    envelope = Paginated[Any].model_validate(payload)
    records = [
        record
        for record in (validate_event_row(row) for row in envelope.records)
        if record is not None
    ]
    return Paginated[Event](
        records=records,
        count=envelope.count,
        total_count=envelope.total_count,
        next=envelope.next,
    )


def build_event_params(
    event_name: str | IntrospectionEventName,
    *,
    limit: int = 100,
    cursor: str | None = None,
    sort: EventSortField | None = None,
    direction: Literal["asc", "desc"] | None = None,
    start_date: str | datetime | None = None,
    end_date: str | datetime | None = None,
    conversation_id: str | None = None,
    service_name: str | None = None,
    environment: str | None = None,
    runtime_group_id: UUID | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    owner_key: str | None = None,
    event_id: builtins.list[str] | None = None,
    conversation_ids: builtins.list[str] | None = None,
    lens: str | None = None,
    pattern_id: str | UUID | None = None,
    include_superseded: bool | None = None,
    severities: builtins.list[str] | None = None,
    runtime_group_unattributed: bool | None = None,
    status: str | None = None,
    automation_id: UUID | str | None = None,
    task_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Fold the shared list/arrow kwargs into the wire query params.

    ``event_name`` is required, exactly one family — the last per-request
    source of heterogeneity. Family-scoped filters (observation:
    ``conversation_ids`` / ``lens`` / ``pattern_id`` / ``include_superseded``
    / ``severities`` / ``runtime_group_unattributed``; pattern: ``lens`` /
    ``status``; automation triggered/skipped: ``automation_id`` /
    ``task_id``) are passed through; the server validates them against the
    requested family's allow-map.
    """
    if not event_name:
        raise ValueError(
            "event_name is required — pass exactly one event family, e.g. "
            "'introspection.observation' (see IntrospectionEventName)"
        )
    return {
        "event_name": str(event_name),
        "limit": limit,
        "next": cursor,
        "sort": sort,
        "direction": direction,
        "start_date": start_date,
        "end_date": end_date,
        "conversation_id": conversation_id,
        "service_name": service_name,
        "environment": environment,
        "runtime_group_id": runtime_group_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "owner_key": owner_key,
        "event_id": event_id,
        "conversation_ids": conversation_ids,
        "lens": lens,
        "pattern_id": pattern_id,
        "include_superseded": include_superseded,
        "severities": severities,
        "runtime_group_unattributed": runtime_group_unattributed,
        "status": status,
        "automation_id": automation_id,
        "task_id": task_id,
    }
