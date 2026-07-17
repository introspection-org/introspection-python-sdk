"""`runner.events.*` namespace: read-only event reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only and mirrors ``runner.conversations``: one cursor-paginated list
read over the append-only ``otel_logs`` store. Every read names its
family — ``event_name`` is **required, exactly one** — so a page is
always homogeneous and each row validates into one member of the
discriminated :data:`~introspection_sdk.schemas.events.Event` union
(common envelope + nested typed ``payload``).

Three response representations share one request contract:

* JSON (default) — the standard cursor envelope
  (:class:`~introspection_sdk.schemas.pagination.Paginated`).
* Arrow (``format="arrow"``) — the same page as an Arrow IPC stream
  (envelope columns + a typed ``payload`` struct column) with pagination
  metadata on response headers, decoded back into the identical envelope
  (see :mod:`introspection_sdk.runner_resources._reads`).
* Columnar (:meth:`Events.arrow`) — the raw ``pyarrow.Table`` per page,
  for callers who want columns rather than models.

**Unknown-family tolerance:** rows whose ``event_name`` is outside the
SDK's known family set are skipped client-side (never raised), counted on
:data:`UNKNOWN_EVENT_SKIPS`, and debug-logged — so a seventh server-side
family doesn't break older SDKs.
"""

from __future__ import annotations

import builtins
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk._http import RawResponse, _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.runner_resources._reads import (
    ARROW_ACCEPT_HEADERS,
    ArrowPageIterator,
    AsyncArrowPageIterator,
    ReadFormat,
    decode_arrow_page,
    resolve_window,
)
from introspection_sdk.schemas.events import (
    KNOWN_EVENT_NAMES,
    Event,
    EventSortField,
    IntrospectionEventName,
)
from introspection_sdk.schemas.pagination import Paginated

logger = logging.getLogger(__name__)

#: One adapter validates a decoded row into the right union member off the
#: top-level ``event_name`` discriminator.
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class UnknownEventCounter:
    """Counts rows skipped because their family is unknown to this SDK."""

    def __init__(self) -> None:
        self.count = 0

    def increment(self, event_name: Any) -> None:
        self.count += 1
        logger.debug(
            "skipping event row with unknown event_name %r "
            "(not in this SDK's typed family set; total skipped: %d)",
            event_name,
            self.count,
        )


#: Process-wide skip counter for unknown-family rows (observability hook).
UNKNOWN_EVENT_SKIPS = UnknownEventCounter()


def validate_event_row(row: dict[str, Any]) -> Event | None:
    """Validate one wire row into the discriminated :data:`Event` union.

    Rows whose ``event_name`` falls outside the known family set are
    skipped (``None``) rather than raised — the closed set may grow
    server-side before this SDK learns the new member.
    """
    if row.get("event_name") not in KNOWN_EVENT_NAMES:
        UNKNOWN_EVENT_SKIPS.increment(row.get("event_name"))
        return None
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
    event_id: builtins.list[str] | None = None,
    conversation_ids: builtins.list[str] | None = None,
    lens: str | None = None,
    pattern_id: str | UUID | None = None,
    include_superseded: bool | None = None,
    severities: builtins.list[str] | None = None,
    runtime_group_unattributed: bool | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Fold the shared list/arrow kwargs into the wire query params.

    ``event_name`` is required, exactly one family — the last per-request
    source of heterogeneity. Family-scoped filters (observation:
    ``conversation_ids`` / ``lens`` / ``pattern_id`` / ``include_superseded``
    / ``severities`` / ``runtime_group_unattributed``; pattern: ``lens`` /
    ``status``) are passed through; the server validates them against the
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
        "event_id": event_id,
        "conversation_ids": conversation_ids,
        "lens": lens,
        "pattern_id": pattern_id,
        "include_superseded": include_superseded,
        "severities": severities,
        "runtime_group_unattributed": runtime_group_unattributed,
        "status": status,
    }


class Events:
    """Read-only Events API (``GET /v1/events``).

    :meth:`list` returns an auto-paging
    :class:`~introspection_sdk.pagination.Pager` over the standard cursor
    envelope's opaque ``next`` token. :meth:`iterate` is a bounded
    convenience generator over the same stream. :meth:`arrow` is the
    columnar accessor — raw ``pyarrow.Table`` pages instead of models.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        format: ReadFormat = "json",
    ) -> Pager[Event, Paginated[Event]]:
        """List events of one family (cursor envelope). Iterate the returned
        :class:`Pager` to stream every event across pages, or call
        ``.page()`` for the first page only.

        ``event_name`` is **required** and names exactly one family — every
        row is that family's typed union member. Family-scoped filters
        beyond the envelope set are server-validated against the requested
        family. ``order`` is an alias for ``direction``; ``start`` /
        ``end`` for ``start_date`` / ``end_date``; ``lookback`` (e.g.
        ``"24h"``) sets ``start_date = now - lookback`` and is mutually
        exclusive with ``start`` / ``end``. ``format="arrow"`` negotiates
        the columnar Arrow stream, decoded back into the same envelope.
        """
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )
        build_event_params(event_name)  # fail fast before any request

        def fetch(cursor: str | None) -> Paginated[Event]:
            params = build_event_params(
                event_name,
                limit=limit,
                cursor=cursor,
                sort=sort,
                direction=direction or order,
                start_date=resolved_start,
                end_date=resolved_end,
                conversation_id=conversation_id,
                service_name=service_name,
                environment=environment,
                runtime_group_id=runtime_group_id,
                trace_id=trace_id,
                span_id=span_id,
                event_id=event_id,
                conversation_ids=conversation_ids,
                lens=lens,
                pattern_id=pattern_id,
                include_superseded=include_superseded,
                severities=severities,
                runtime_group_unattributed=runtime_group_unattributed,
                status=status,
            )
            if format == "arrow":
                raw = self._http.request(
                    "GET",
                    "/v1/events",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, validate_event_row)
            payload = self._http.request("GET", "/v1/events", params=params)
            return validate_event_page(payload)

        return cursor_paginate(fetch, start=next)

    def iterate(
        self,
        event_name: str | IntrospectionEventName,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> Iterator[Event]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every event. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`.
        """
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        for record in self.list(event_name, **kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

    def arrow(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
    ) -> ArrowPageIterator:
        """Columnar accessor: iterate one ``pyarrow.Table`` per server page
        (constant memory — envelope columns + the family's typed ``payload``
        struct column), or call ``.read_all()`` to concatenate every page
        into one Table. Same filters as :meth:`list`; requires the
        ``[arrow]`` extra.
        """
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )
        build_event_params(event_name)  # fail fast before any request

        def fetch(cursor: str | None) -> RawResponse:
            params = build_event_params(
                event_name,
                limit=limit,
                cursor=cursor,
                sort=sort,
                direction=direction or order,
                start_date=resolved_start,
                end_date=resolved_end,
                conversation_id=conversation_id,
                service_name=service_name,
                environment=environment,
                runtime_group_id=runtime_group_id,
                trace_id=trace_id,
                span_id=span_id,
                event_id=event_id,
                conversation_ids=conversation_ids,
                lens=lens,
                pattern_id=pattern_id,
                include_superseded=include_superseded,
                severities=severities,
                runtime_group_unattributed=runtime_group_unattributed,
                status=status,
            )
            raw = self._http.request(
                "GET",
                "/v1/events",
                params=params,
                headers=ARROW_ACCEPT_HEADERS,
                expect="raw",
            )
            assert isinstance(raw, RawResponse)
            return raw

        return ArrowPageIterator(fetch, start=next)


class AsyncEvents:
    """Async twin of :class:`Events`. Read-only (``GET /v1/events``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[Event, Paginated[Event]]:
        """List events of one family (cursor envelope). ``await`` the
        returned :class:`AsyncPager` for the first page, or ``async for``
        it to stream every event across pages. See :meth:`Events.list` for
        the param semantics."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )
        build_event_params(event_name)  # fail fast before any request

        async def fetch(cursor: str | None) -> Paginated[Event]:
            params = build_event_params(
                event_name,
                limit=limit,
                cursor=cursor,
                sort=sort,
                direction=direction or order,
                start_date=resolved_start,
                end_date=resolved_end,
                conversation_id=conversation_id,
                service_name=service_name,
                environment=environment,
                runtime_group_id=runtime_group_id,
                trace_id=trace_id,
                span_id=span_id,
                event_id=event_id,
                conversation_ids=conversation_ids,
                lens=lens,
                pattern_id=pattern_id,
                include_superseded=include_superseded,
                severities=severities,
                runtime_group_unattributed=runtime_group_unattributed,
                status=status,
            )
            if format == "arrow":
                raw = await self._http.request(
                    "GET",
                    "/v1/events",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, validate_event_row)
            payload = await self._http.request(
                "GET", "/v1/events", params=params
            )
            return validate_event_page(payload)

        return async_cursor_paginate(fetch, start=next)

    async def iterate(
        self,
        event_name: str | IntrospectionEventName,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Event]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every event. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`.
        """
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        async for record in self.list(event_name, **kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

    def arrow(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
    ) -> AsyncArrowPageIterator:
        """Columnar accessor: ``async for`` one ``pyarrow.Table`` per server
        page, or ``await .read_all()`` to concatenate every page into one
        Table. Same filters as :meth:`list`; requires the ``[arrow]``
        extra."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )
        build_event_params(event_name)  # fail fast before any request

        async def fetch(cursor: str | None) -> RawResponse:
            params = build_event_params(
                event_name,
                limit=limit,
                cursor=cursor,
                sort=sort,
                direction=direction or order,
                start_date=resolved_start,
                end_date=resolved_end,
                conversation_id=conversation_id,
                service_name=service_name,
                environment=environment,
                runtime_group_id=runtime_group_id,
                trace_id=trace_id,
                span_id=span_id,
                event_id=event_id,
                conversation_ids=conversation_ids,
                lens=lens,
                pattern_id=pattern_id,
                include_superseded=include_superseded,
                severities=severities,
                runtime_group_unattributed=runtime_group_unattributed,
                status=status,
            )
            raw = await self._http.request(
                "GET",
                "/v1/events",
                params=params,
                headers=ARROW_ACCEPT_HEADERS,
                expect="raw",
            )
            assert isinstance(raw, RawResponse)
            return raw

        return AsyncArrowPageIterator(fetch, start=next)
