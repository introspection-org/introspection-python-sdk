"""Contract tests for the read-only ``runner.events`` namespace.

Mirrors ``test_conversations.py``: the cursor ``next`` paging protocol, the
required single-family ``event_name`` selection, the discriminated typed
``Event`` union (envelope + nested ``payload``), the unknown-family skip
tolerance, the ergonomic window params (``order`` / ``start`` / ``end`` /
``lookback``), the bounded ``iterate`` generator, the optional Arrow decode
path, and the columnar ``.arrow()`` accessor.

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
from introspection_sdk.runner_resources.events import UNKNOWN_EVENT_SKIPS
from introspection_sdk.schemas.events import (
    FeedbackEvent,
    IntrospectionEventName,
    JudgementEvent,
    ObservationEvent,
    PatternEvent,
)

from .conftest import FakeAPI

RUNTIME_GROUP_ID = "22222222-2222-2222-2222-222222222222"
PATTERN_ID = "pat_777"
OBSERVATION_ID = "88888888-8888-8888-8888-888888888888"


def envelope(
    event_name: str, payload: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """One wire event row: common envelope + nested typed payload."""
    row: dict[str, Any] = {
        "id": "evt-1",
        "timestamp": "2025-01-01T00:00:00Z",
        "event_name": event_name,
        "service_name": "agent-runtime",
        "payload": payload,
    }
    row.update(overrides)
    return row


def observation_event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "observation_id": OBSERVATION_ID,
        "lens": "task_resolution",
        "summary": "did the thing",
        "severity": "high",
        "pattern_id": PATTERN_ID,
        "assignment_score": 0.93,
        "assignment_method": "hdbscan",
    }
    payload.update(overrides.pop("payload", {}))
    return envelope("introspection.observation", payload, **overrides)


def pattern_event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pattern_id": PATTERN_ID,
        "action": "created",
        "name": "premature handoff",
        "status": "active",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "last_detected_at": "2025-01-03T00:00:00Z",
    }
    payload.update(overrides.pop("payload", {}))
    return envelope("introspection.pattern", payload, **overrides)


def feedback_event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "thumbs_up",
        "comments": "great answer",
        "value": 1.0,
        "user_id": "user-1",
        "sentiment": "positive",
        "properties": {"surface": "chat"},
    }
    payload.update(overrides.pop("payload", {}))
    return envelope("introspection.feedback", payload, **overrides)


def judgement_event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "judgement_id": "jdg-1",
        "judge_id": "judge-1",
        "result": "pass",
        "definition_hash": "abc",
        "contract_version": "1",
    }
    payload.update(overrides.pop("payload", {}))
    return envelope("introspection.judgement", payload, **overrides)


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


# --- required event_name --------------------------------------------


def test_list_requires_event_name(fake_api: FakeAPI):
    events = _events(fake_api)
    with pytest.raises(TypeError):
        events.list()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="event_name is required"):
        events.list("")
    # Nothing was sent.
    assert fake_api.requests == []


def test_iterate_requires_event_name(fake_api: FakeAPI):
    events = _events(fake_api)
    with pytest.raises(TypeError):
        list(events.iterate())  # type: ignore[call-arg]
    assert fake_api.requests == []


def test_arrow_requires_event_name(fake_api: FakeAPI):
    events = _events(fake_api)
    with pytest.raises(TypeError):
        events.arrow()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="event_name is required"):
        events.arrow("")
    assert fake_api.requests == []


# --- per-family JSON round-trips ------------------------------------


def test_list_observation_family_typed_payload(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=cursor_page([observation_event()], None),
    )
    events = _events(fake_api)

    page = events.list(
        IntrospectionEventName.OBSERVATION,
        limit=25,
        lens="task_resolution",
        pattern_id=PATTERN_ID,
        order="asc",
        severities=["high", "medium"],
        include_superseded=True,
        conversation_ids=["conv-1", "conv-2"],
    ).page()

    assert len(page.records) == 1
    record = page.records[0]
    assert isinstance(record, ObservationEvent)
    assert record.event_name == IntrospectionEventName.OBSERVATION
    assert record.payload.observation_id == UUID(OBSERVATION_ID)
    assert record.payload.lens == "task_resolution"
    assert record.payload.severity == "high"
    assert record.payload.pattern_id == PATTERN_ID
    assert record.payload.assignment_score == 0.93
    assert record.payload.assignment_method == "hdbscan"

    req = fake_api.last_request
    assert req.path == "/v1/events"
    assert req.params.get("event_name") == "introspection.observation"
    assert req.params.get("limit") == "25"
    assert req.params.get("lens") == "task_resolution"
    assert req.params.get("pattern_id") == PATTERN_ID
    assert req.params.get("include_superseded") == "true"
    # order folds into direction.
    assert req.params.get("direction") == "asc"
    assert req.url.params.get_list("severities") == ["high", "medium"]
    assert req.url.params.get_list("conversation_ids") == ["conv-1", "conv-2"]
    # Retired params never leave the client.
    for gone in ("grain", "include", "event_name_prefix", "q", "q_regex"):
        assert req.params.get(gone) is None


def test_list_pattern_family_typed_payload(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/events", json_body=cursor_page([pattern_event()], None)
    )
    events = _events(fake_api)

    page = events.list(
        "introspection.pattern", lens="task_resolution", status="active"
    ).page()

    record = page.records[0]
    assert isinstance(record, PatternEvent)
    assert record.payload.pattern_id == PATTERN_ID
    assert record.payload.action == "created"
    assert record.payload.status == "active"
    assert record.payload.created_at is not None
    assert record.payload.last_detected_at is not None

    req = fake_api.last_request
    assert req.params.get("event_name") == "introspection.pattern"
    assert req.params.get("status") == "active"
    assert req.params.get("lens") == "task_resolution"


def test_list_feedback_family_typed_payload(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/events", json_body=cursor_page([feedback_event()], None)
    )
    events = _events(fake_api)

    page = events.list("introspection.feedback").page()

    record = page.records[0]
    assert isinstance(record, FeedbackEvent)
    assert record.payload.name == "thumbs_up"
    assert record.payload.comments == "great answer"
    assert record.payload.value == 1.0
    assert record.payload.user_id == "user-1"
    assert record.payload.sentiment == "positive"
    assert record.payload.properties == {"surface": "chat"}
    assert (
        fake_api.last_request.params.get("event_name")
        == "introspection.feedback"
    )


def test_list_judgement_family_typed_payload(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/events", json_body=cursor_page([judgement_event()], None)
    )
    events = _events(fake_api)

    page = events.list(IntrospectionEventName.JUDGEMENT).page()

    record = page.records[0]
    assert isinstance(record, JudgementEvent)
    assert record.payload.judgement_id == "jdg-1"
    assert record.payload.result == "pass"


# --- unknown-family tolerance ---------------------------------------


def test_unknown_family_row_skipped_not_raised(fake_api: FakeAPI):
    unknown = envelope(
        "introspection.shiny_new_thing", {"whatever": 1}, id="evt-unknown"
    )
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=cursor_page([feedback_event(), unknown], None),
    )
    events = _events(fake_api)
    before = UNKNOWN_EVENT_SKIPS.count

    page = events.list("introspection.feedback").page()

    # The unknown row was dropped, the known one survived, nothing raised.
    assert [type(r) for r in page.records] == [FeedbackEvent]
    assert UNKNOWN_EVENT_SKIPS.count == before + 1
    # The wire-page count is preserved even though a row was skipped.
    assert page.count == 2


# --- paging ----------------------------------------------------------


def test_list_lookback_computes_start_date(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/events", json_body=cursor_page([], None))
    events = _events(fake_api)

    events.list("introspection.feedback", lookback="24h").page()

    req = fake_api.last_request
    assert req.params.get("start_date") is not None
    assert req.params.get("end_date") is None


def test_list_lookback_and_start_raises_before_request(fake_api: FakeAPI):
    events = _events(fake_api)
    with pytest.raises(ValueError):
        events.list(
            "introspection.feedback",
            lookback="24h",
            start="2025-01-01T00:00:00Z",
        )
    # Nothing was sent.
    assert fake_api.requests == []


def test_iter_drives_cursor_next(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page([feedback_event(id="evt-1")], "cursor-2"),
                cursor_page([feedback_event(id="evt-2")], None),
            ]
        ),
    )
    events = _events(fake_api)

    records = list(events.list("introspection.feedback"))

    assert [r.id for r in records] == ["evt-1", "evt-2"]
    assert fake_api.requests[1].params.get("next") == "cursor-2"


def test_iterate_bounds_max_items(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page(
                    [feedback_event(id="evt-1"), feedback_event(id="evt-2")],
                    "cursor-2",
                ),
                cursor_page([feedback_event(id="evt-3")], None),
            ]
        ),
    )
    events = _events(fake_api)

    records = list(events.iterate("introspection.feedback", max_items=1))

    assert [r.id for r in records] == ["evt-1"]
    # Bounded: only the first page was fetched.
    assert len(fake_api.requests) == 1


# --- Arrow decode path ----------------------------------------------


def _arrow_stream(rows: list[dict[str, Any]]) -> bytes:
    """Encode rows the way the server does: envelope columns + a nested
    ``payload`` struct column (``from_pylist`` infers the struct type)."""
    table = pa.Table.from_pylist(rows)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def test_list_arrow_decodes_payload_struct_and_headers(fake_api: FakeAPI):
    rows = [observation_event(id="evt-1"), observation_event(id="evt-2")]
    body = _arrow_stream(rows)
    # The wire schema really is envelope columns + one struct column.
    schema = pa.ipc.open_stream(pa.BufferReader(body)).schema
    assert pa.types.is_struct(schema.field("payload").type)
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

    page = events.list("introspection.observation", format="arrow").page()

    # Accept header negotiated the Arrow stream.
    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert [r.id for r in page.records] == ["evt-1", "evt-2"]
    assert all(isinstance(r, ObservationEvent) for r in page.records)
    assert page.records[0].payload.observation_id == UUID(OBSERVATION_ID)
    assert page.records[0].payload.pattern_id == PATTERN_ID
    assert page.next == "cursor-2"
    assert page.count == 2
    assert page.total_count == 9


def test_list_arrow_empty_page_decodes_zero_records(fake_api: FakeAPI):
    # An empty page has no body at all, exercising the empty-content guard
    # in ``decode_arrow_table`` — no reader is opened.
    fake_api.add(
        "GET",
        "/v1/events",
        content=b"",
        headers={"X-Result-Count": "0", "X-Total-Count": "0"},
    )
    events = _events(fake_api)

    page = events.list("introspection.feedback", format="arrow").page()

    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert page.records == []
    assert page.count == 0
    assert page.total_count == 0
    assert page.next is None


def test_list_arrow_skips_unknown_family_rows(fake_api: FakeAPI):
    body = _arrow_stream(
        [
            feedback_event(id="evt-1"),
            envelope(
                "introspection.shiny_new_thing",
                {"name": "?"},
                id="evt-unknown",
            ),
        ]
    )
    fake_api.add("GET", "/v1/events", content=body)
    events = _events(fake_api)
    before = UNKNOWN_EVENT_SKIPS.count

    page = events.list("introspection.feedback", format="arrow").page()

    assert [r.id for r in page.records] == ["evt-1"]
    assert UNKNOWN_EVENT_SKIPS.count == before + 1


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
        decode_arrow_page(raw, lambda row: row)


def test_iter_arrow_pages_via_next_header(fake_api: FakeAPI):
    page1 = _arrow_stream([feedback_event(id="evt-1")])
    page2 = _arrow_stream([feedback_event(id="evt-2")])
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

    records = list(events.list("introspection.feedback", format="arrow"))

    assert [r.id for r in records] == ["evt-1", "evt-2"]
    assert fake_api.requests[1].params.get("next") == "cursor-2"


# --- columnar .arrow() accessor -------------------------------------


def test_arrow_accessor_yields_tables_per_page(fake_api: FakeAPI):
    page1 = _arrow_stream(
        [feedback_event(id="evt-1"), feedback_event(id="evt-2")]
    )
    page2 = _arrow_stream([feedback_event(id="evt-3")])
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

    tables = list(events.arrow("introspection.feedback", limit=2))

    assert [t.num_rows for t in tables] == [2, 1]
    assert all(isinstance(t, pa.Table) for t in tables)
    assert pa.types.is_struct(tables[0].schema.field("payload").type)
    assert (
        fake_api.requests[0].params.get("event_name")
        == "introspection.feedback"
    )
    assert (
        fake_api.requests[0].headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert fake_api.requests[1].params.get("next") == "cursor-2"


def test_arrow_accessor_read_all_concatenates(fake_api: FakeAPI):
    page1 = _arrow_stream([feedback_event(id="evt-1")])
    page2 = _arrow_stream([feedback_event(id="evt-2")])
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

    table = events.arrow("introspection.feedback").read_all()

    assert isinstance(table, pa.Table)
    assert table.num_rows == 2
    assert table.column("id").to_pylist() == ["evt-1", "evt-2"]


def test_arrow_accessor_read_all_empty(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/events", content=b"")
    events = _events(fake_api)

    table = events.arrow("introspection.feedback").read_all()

    assert isinstance(table, pa.Table)
    assert table.num_rows == 0


# --- async twin -----------------------------------------------------


async def test_async_list_arrow_decodes_body_and_headers(fake_api: FakeAPI):
    body = _arrow_stream(
        [observation_event(id="evt-1"), observation_event(id="evt-2")]
    )
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

    page = await events.list(
        "introspection.observation", format="arrow"
    ).page()

    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert [r.id for r in page.records] == ["evt-1", "evt-2"]
    assert all(isinstance(r, ObservationEvent) for r in page.records)
    assert page.next == "cursor-2"
    assert page.count == 2
    assert page.total_count == 9


async def test_async_list_and_iterate(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/events",
        _sequence_handler(
            [
                cursor_page([feedback_event(id="evt-1")], "cursor-2"),
                cursor_page([feedback_event(id="evt-2")], None),
            ]
        ),
    )
    events = AsyncEvents(fake_api.async_client())

    collected = [
        r.id
        async for r in events.iterate("introspection.feedback", max_items=2)
    ]

    assert collected == ["evt-1", "evt-2"]


async def test_async_arrow_accessor(fake_api: FakeAPI):
    page1 = _arrow_stream([feedback_event(id="evt-1")])
    page2 = _arrow_stream([feedback_event(id="evt-2")])
    responses = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler("GET", "/v1/events", lambda _req: next(responses))
    events = AsyncEvents(fake_api.async_client())

    tables = [t async for t in events.arrow("introspection.feedback")]
    assert [t.num_rows for t in tables] == [1, 1]

    responses2 = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler("GET", "/v1/events", lambda _req: next(responses2))
    table = await events.arrow("introspection.feedback").read_all()
    assert table.num_rows == 2


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
