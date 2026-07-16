"""`runner.events.*` namespace: read-only event reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only and mirrors ``runner.conversations``: one cursor-paginated list
read over the append-only ``otel_logs`` store, with a ``grain`` selecting
the raw-event / observation / pattern projection.

Two response representations share one request contract:

* JSON (default) — the standard cursor envelope
  (:class:`~introspection_sdk.schemas.pagination.Paginated`).
* Arrow (``format="arrow"``) — the same page as an Arrow IPC stream with
  pagination metadata on response headers, decoded back into the identical
  envelope (see :mod:`introspection_sdk.runner_resources._reads`).
"""

from __future__ import annotations

import builtins
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
    ReadFormat,
    decode_arrow_page,
    resolve_window,
)
from introspection_sdk.schemas.events import (
    EventGrain,
    EventInclude,
    EventRecord,
    EventSortField,
)
from introspection_sdk.schemas.pagination import Paginated

# One adapter validates a decoded row into the right grain model. The three
# grain models have disjoint required fields (``timestamp`` / ``observed_at`` /
# ``pattern_id``), so the union routes each homogeneous page unambiguously.
_EVENT_RECORD_ADAPTER: TypeAdapter[EventRecord] = TypeAdapter(EventRecord)


def _validate_event(row: dict[str, Any]) -> EventRecord:
    return _EVENT_RECORD_ADAPTER.validate_python(row)


class Events:
    """Read-only Events API (``GET /v1/events``).

    :meth:`list` returns an auto-paging
    :class:`~introspection_sdk.pagination.Pager` over the standard cursor
    envelope's opaque ``next`` token. :meth:`iterate` is a bounded
    convenience generator over the same stream.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        grain: EventGrain = "raw",
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
        conversation_ids: builtins.list[str] | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        lens: str | None = None,
        pattern_id: UUID | None = None,
        status: str | None = None,
        severities: builtins.list[str] | None = None,
        event_name: str | None = None,
        event_name_prefix: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        q: str | None = None,
        q_regex: str | None = None,
        include: builtins.list[EventInclude] | None = None,
        format: ReadFormat = "json",
    ) -> Pager[EventRecord, Paginated[EventRecord]]:
        """List events (cursor envelope). Iterate the returned :class:`Pager`
        to stream every event across pages, or call ``.page()`` for the first
        page only.

        ``grain`` selects the projection (``raw`` /
        ``introspection.observation`` / ``introspection.pattern``); the
        available filters depend on the grain (the DP rejects mismatches with
        a ``400``). ``order`` is an alias for ``direction``; ``start`` /
        ``end`` for ``start_date`` / ``end_date``; ``lookback`` (e.g.
        ``"24h"``) sets ``start_date = now - lookback`` and is mutually
        exclusive with ``start`` / ``end``. ``format="arrow"`` negotiates the
        columnar Arrow stream, decoded back into the same envelope.
        """
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        def fetch(cursor: str | None) -> Paginated[EventRecord]:
            params: dict[str, Any] = {
                "grain": grain,
                "limit": limit,
                "next": cursor,
                "sort": sort,
                "direction": direction or order,
                "start_date": resolved_start,
                "end_date": resolved_end,
                "conversation_id": conversation_id,
                "conversation_ids": conversation_ids,
                "service_name": service_name,
                "environment": environment,
                "runtime_group_id": runtime_group_id,
                "lens": lens,
                "pattern_id": pattern_id,
                "status": status,
                "severities": severities,
                "event_name": event_name,
                "event_name_prefix": event_name_prefix,
                "trace_id": trace_id,
                "span_id": span_id,
                "event_id": event_id,
                "q": q,
                "q_regex": q_regex,
                "include": include,
            }
            if format == "arrow":
                raw = self._http.request(
                    "GET",
                    "/v1/events",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, _validate_event)
            payload = self._http.request("GET", "/v1/events", params=params)
            return Paginated[EventRecord].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def iterate(
        self,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> Iterator[EventRecord]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every event. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`.
        """
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        for record in self.list(**kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return


class AsyncEvents:
    """Async twin of :class:`Events`. Read-only (``GET /v1/events``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        grain: EventGrain = "raw",
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
        conversation_ids: builtins.list[str] | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        lens: str | None = None,
        pattern_id: UUID | None = None,
        status: str | None = None,
        severities: builtins.list[str] | None = None,
        event_name: str | None = None,
        event_name_prefix: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        event_id: builtins.list[str] | None = None,
        q: str | None = None,
        q_regex: str | None = None,
        include: builtins.list[EventInclude] | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[EventRecord, Paginated[EventRecord]]:
        """List events (cursor envelope). ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to stream
        every event across pages. See :meth:`Events.list` for the param
        semantics."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        async def fetch(cursor: str | None) -> Paginated[EventRecord]:
            params: dict[str, Any] = {
                "grain": grain,
                "limit": limit,
                "next": cursor,
                "sort": sort,
                "direction": direction or order,
                "start_date": resolved_start,
                "end_date": resolved_end,
                "conversation_id": conversation_id,
                "conversation_ids": conversation_ids,
                "service_name": service_name,
                "environment": environment,
                "runtime_group_id": runtime_group_id,
                "lens": lens,
                "pattern_id": pattern_id,
                "status": status,
                "severities": severities,
                "event_name": event_name,
                "event_name_prefix": event_name_prefix,
                "trace_id": trace_id,
                "span_id": span_id,
                "event_id": event_id,
                "q": q,
                "q_regex": q_regex,
                "include": include,
            }
            if format == "arrow":
                raw = await self._http.request(
                    "GET",
                    "/v1/events",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, _validate_event)
            payload = await self._http.request(
                "GET", "/v1/events", params=params
            )
            return Paginated[EventRecord].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def iterate(
        self,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[EventRecord]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every event. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`.
        """
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        async for record in self.list(**kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return
