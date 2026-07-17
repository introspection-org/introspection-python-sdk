"""Contract tests for the read-only ``runner.events`` namespace.

Mirrors ``test_conversations.py``: the cursor ``next`` paging protocol, the
``grain`` projection selection, the ergonomic window params (``order`` /
``start`` / ``end`` / ``lookback``), the bounded ``iterate`` generator, and
the optional Arrow decode path.

Driven through the offline :class:`FakeAPI` transport from ``conftest.py`` —
nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

import builtins
import io
from typing import Any
from uuid import UUID

import httpx
import pyarrow as pa
import pytest

from introspection_sdk.runner_resources import AsyncEvents, Events
from introspection_sdk.runner_resources._reads import (
    ARROW_STREAM_MEDIA_TYPE,
    parse_lookback,
    resolve_window,
)
from introspection_sdk.schemas.events import (
    EventRecord,
    LensObservation,
    RawEvent,
)

from .conftest import FakeAPI

RUNTIME_GROUP_ID = "22222222-2222-2222-2222-222222222222"
PATTERN_ID = "77777777-7777-7777-7777-777777777777"
OBSERVATION_ID = "88888888-8888-8888-8888-888888888888"


def _ids(records: list[EventRecord]) -> list[str | UUID]:
    """Collect ``id`` across a page, narrowing off the id-less pattern grain."""
    return [r.id for r in records if isinstance(r, RawEvent | LensObservation)]


def raw_event(**overrides: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "id": "evt-1",
        "timestamp": "2025-01-01T00:00:00Z",
        "event_name": "gen_ai.user.message",
        "service_name": "agent-runtime",
    }
    ev.update(overrides)
    return ev


def observation(**overrides: Any) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "id": OBSERVATION_ID,
        "lens": "task_resolution",
        "summary": "did the thing",
        "observed_at": "2025-01-01T00:00:00Z",
    }
    obs.update(overrides)
    return obs


def cursor_page(
    records: list[dict[str, Any]], next_token: str | None
) -> dict[str, Any]:
    return {
        "records": records,
        "count": len(records),
        "total_count": len(records),
        "next": next_token,
    }


def _sequence_handler(pages: list[dict[str, Any]]):
    it = iter(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(it))

    return handler


def _events(fake_api: FakeAPI) -> Events:
    return Events(fake_api.client())


# --- window helper --------------------------------------------------


def test_parse_lookback_units():
    assert parse_lookback("30s").total_seconds() == 30
    assert parse_lookback("15m").total_seconds() == 900
    assert parse_lookback("24h").total_seconds() == 86400
    assert parse_lookback("7d").total_seconds() == 604800
    assert parse_lookback("2w").total_seconds() == 1209600


def test_parse_lookback_rejects_garbage():
    with pytest.raises(ValueError):
        parse_lookback("soon")
    with pytest.raises(ValueError):
        parse_lookback("0h")


def test_resolve_window_lookback_mutually_exclusive():
    with pytest.raises(ValueError):
        resolve_window(start="2025-01-01T00:00:00Z", lookback="24h")
    with pytest.raises(ValueError):
        resolve_window(end="2025-01-01T00:00:00Z", lookback="24h")
    with pytest.raises(ValueError):
        resolve_window(start_date="2025-01-01T00:00:00Z", lookback="24h")


def test_resolve_window_aliases():
    start, end = resolve_window(start="s", end="e")
    assert start == "s"
    assert end == "e"


# --- list() ---------------------------------------------------------


def test_list_passes_grain_and_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/events", json_body=cursor_page([observation()], None)
    )
    events = _events(fake_api)

    page = events.list(
        grain="introspection.observation",
        limit=25,
        lens="task_resolution",
        pattern_id=UUID(PATTERN_ID),
        order="asc",
        severities=["high", "medium"],
    )

    assert len(page.records) == 1
    assert isinstance(page.records[0], LensObservation)
    req = fake_api.last_request
    assert req.path == "/v1/events"
    assert req.params.get("grain") == "introspection.observation"
    assert req.params.get("limit") == "25"
    assert req.params.get("lens") == "task_resolution"
    assert req.params.get("pattern_id") == PATTERN_ID
    # order folds into direction.
    assert req.params.get("direction") == "asc"
    assert req.url.params.get_list("severities") == ["high", "medium"]


def test_list_default_grain_is_raw(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/events", json_body=cursor_page([raw_event()], None)
    )
    events = _events(fake_api)

    page = events.list()

    assert isinstance(page.records[0], RawEvent)
    assert fake_api.last_request.params.get("grain") == "raw"


def test_list_lookback_computes_start_date(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/events", json_body=cursor_page([], None))
    events = _events(fake_api)

    events.list(lookback="24h").page()

    req = fake_api.last_request
    assert req.params.get("start_date") is not None
    assert req.params.get("end_date") is None


def test_list_lookback_and_start_raises_before_request(fake_api: FakeAPI):
    events = _events(fake_api)
    with pytest.raises(ValueError):
        events.list(lookback="24h", start="2025-01-01T00:00:00Z")
    # Nothing was sent.
    assert fake_api.requests == []


def test_iter_drives_cursor_next(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page([raw_event(id="evt-1")], "cursor-2"),
                cursor_page([raw_event(id="evt-2")], None),
            ]
        ),
    )
    events = _events(fake_api)

    records = list(events.list())

    assert _ids(records) == ["evt-1", "evt-2"]
    assert fake_api.requests[1].params.get("next") == "cursor-2"


def test_iterate_bounds_max_items(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page(
                    [raw_event(id="evt-1"), raw_event(id="evt-2")], "cursor-2"
                ),
                cursor_page([raw_event(id="evt-3")], None),
            ]
        ),
    )
    events = _events(fake_api)

    records = list(events.iterate(max_items=1))

    assert _ids(records) == ["evt-1"]
    # Bounded: only the first page was fetched.
    assert len(fake_api.requests) == 1


# --- Arrow decode path ----------------------------------------------


def _arrow_stream(rows: list[dict[str, Any]]) -> bytes:
    table = pa.Table.from_pylist(rows)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def test_list_arrow_decodes_body_and_headers(fake_api: FakeAPI):
    body = _arrow_stream([raw_event(id="evt-1"), raw_event(id="evt-2")])
    fake_api.add(
        "GET",
        "/v1/events",
        content=body,
        headers={
            "X-Next-Cursor": "cursor-2",
            "X-Result-Count": "2",
            "X-Total-Count": "9",
            "X-Truncated": "true",
        },
    )
    events = _events(fake_api)

    page = events.list(format="arrow").page()

    # Accept header negotiated the Arrow stream.
    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert _ids(page.records) == ["evt-1", "evt-2"]
    assert page.next == "cursor-2"
    assert page.count == 2
    assert page.total_count == 9


def test_list_arrow_empty_page_decodes_zero_records(fake_api: FakeAPI):
    # An empty page has no body at all, exercising the ``if raw.content:``
    # guard in ``decode_arrow_page`` — no reader is opened.
    fake_api.add(
        "GET",
        "/v1/events",
        content=b"",
        headers={"X-Result-Count": "0", "X-Total-Count": "0"},
    )
    events = _events(fake_api)

    page = events.list(format="arrow").page()

    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert page.records == []
    assert page.count == 0
    assert page.total_count == 0
    assert page.next is None


def test_arrow_decode_without_pyarrow_raises_extra_hint(monkeypatch):
    # Simulate the ``[arrow]`` extra not being installed: force the local
    # ``import pyarrow`` in ``decode_arrow_page`` to fail and assert the
    # error steers the caller at the extra.
    from introspection_sdk._http import RawResponse
    from introspection_sdk.runner_resources._reads import decode_arrow_page

    real_import = builtins.__import__

    def _no_pyarrow(name: str, *args: Any, **kwargs: Any):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ModuleNotFoundError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyarrow)

    raw = RawResponse(content=b"anything", headers=httpx.Headers())
    with pytest.raises(ImportError, match=r"introspection-sdk\[arrow\]"):
        # The import guard fires before ``validate`` is ever called.
        decode_arrow_page(raw, lambda row: raw_event(**row))


def test_iter_arrow_pages_via_next_header(fake_api: FakeAPI):
    page1 = _arrow_stream([raw_event(id="evt-1")])
    page2 = _arrow_stream([raw_event(id="evt-2")])
    responses = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler("GET", "/v1/events", lambda _req: next(responses))
    events = _events(fake_api)

    records = list(events.list(format="arrow"))

    assert _ids(records) == ["evt-1", "evt-2"]
    assert fake_api.requests[1].params.get("next") == "cursor-2"


# --- async twin -----------------------------------------------------


async def test_async_list_arrow_decodes_body_and_headers(fake_api: FakeAPI):
    body = _arrow_stream([raw_event(id="evt-1"), raw_event(id="evt-2")])
    fake_api.add(
        "GET",
        "/v1/events",
        content=body,
        headers={
            "X-Next-Cursor": "cursor-2",
            "X-Result-Count": "2",
            "X-Total-Count": "9",
        },
    )
    events = AsyncEvents(fake_api.async_client())

    page = await events.list(format="arrow").page()

    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert _ids(page.records) == ["evt-1", "evt-2"]
    assert page.next == "cursor-2"
    assert page.count == 2
    assert page.total_count == 9


async def test_async_list_and_iterate(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page([raw_event(id="evt-1")], "cursor-2"),
                cursor_page([raw_event(id="evt-2")], None),
            ]
        ),
    )
    events = AsyncEvents(fake_api.async_client())

    collected = [
        r.id
        async for r in events.iterate(max_items=2)
        if isinstance(r, RawEvent | LensObservation)
    ]

    assert collected == ["evt-1", "evt-2"]


# --- Runner wiring --------------------------------------------------


def test_runner_exposes_events_and_metrics():
    from introspection_sdk._errors import RunnerExpiredError
    from introspection_sdk.runner import Runner
    from introspection_sdk.runner_resources import Metrics

    from .conftest import runner_spec_payload

    spec = runner_spec_payload()
    runner = Runner(spec, refresher=lambda: spec)
    assert isinstance(runner.events, Events)
    assert isinstance(runner.metrics, Metrics)
    runner.close()
    with pytest.raises(RunnerExpiredError):
        _ = runner.events
    with pytest.raises(RunnerExpiredError):
        _ = runner.metrics
