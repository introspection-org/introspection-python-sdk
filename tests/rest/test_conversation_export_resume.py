"""Oldest-first conversation reads: the resumable export and ``items`` order.

``open_export`` sends ``direction`` / ``next``, surfaces the
``Introspection-Next`` response header before the body streams, and reports
the ``204`` "nothing newer" answer as ``nothing_newer`` with the cursor kept.
``items.list`` sends ``direction=asc|desc``.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx2 as httpx
import pytest

from introspection_sdk._errors import IntrospectionAPIError
from introspection_sdk.runner_resources import (
    AsyncConversationExport,
    AsyncConversations,
    ConversationExport,
    Conversations,
)
from introspection_sdk.runner_resources.conversations import (
    INTROSPECTION_NEXT_HEADER,
)

from .conftest import FakeAPI
from .test_conversations import jsonl_body, make_item, make_page

EXPORT = "/v1/conversations/conv-1/export"
ITEMS = "/v1/conversations/conv-1/items"

#: Cursors embed a nanosecond timestamp. The leading zero and the length
#: (past 2**53) catch any SDK that parses one into a number on the way.
CURSOR = "00017314560001234567891:trace-1:span-2"
NEWER_CURSOR = "00017314560009876543210:trace-1:span-9"


def _conversations(fake_api: FakeAPI) -> Conversations:
    return Conversations(fake_api.client())


def test_open_export_asc_sends_direction_and_surfaces_the_cursor(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        EXPORT,
        content=jsonl_body("span-1", "span-2"),
        headers={INTROSPECTION_NEXT_HEADER: CURSOR},
    )

    with _conversations(fake_api).open_export(
        "conv-1", direction="asc", agent="root"
    ) as export:
        assert isinstance(export, ConversationExport)
        spans = list(export.iter_spans())

    assert export.next == CURSOR
    assert export.nothing_newer is False
    assert export.status_code == 200
    assert [span.span_id for span in spans] == ["span-1", "span-2"]
    request = fake_api.last_request
    assert request.headers["accept"] == "application/x-ndjson"
    assert dict(request.params) == {"agent": "root", "direction": "asc"}


def test_open_export_reads_the_cursor_before_the_body(fake_api: FakeAPI):
    pulled: list[bytes] = []

    def body() -> Iterator[bytes]:
        for chunk in (jsonl_body("span-1"), jsonl_body("span-2")):
            pulled.append(chunk)
            yield chunk

    fake_api.add_handler(
        "GET",
        EXPORT,
        lambda _request: httpx.Response(
            200, headers={INTROSPECTION_NEXT_HEADER: CURSOR}, content=body()
        ),
    )

    with _conversations(fake_api).open_export(
        "conv-1", direction="asc"
    ) as export:
        # The header is the resume point; it is known with nothing read yet.
        assert export.next == CURSOR
        assert pulled == []
        spans = list(export.iter_spans())

    assert [span.span_id for span in spans] == ["span-1", "span-2"]


def test_open_export_passes_the_cursor_back_verbatim(fake_api: FakeAPI):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["next"] == CURSOR
        return httpx.Response(
            200,
            headers={INTROSPECTION_NEXT_HEADER: NEWER_CURSOR},
            content=jsonl_body("span-3"),
        )

    fake_api.add_handler("GET", EXPORT, handler)

    with _conversations(fake_api).open_export("conv-1", next=CURSOR) as export:
        spans = list(export.iter_spans())

    # `next` implies oldest-first; the SDK sends no direction of its own.
    assert dict(fake_api.last_request.params) == {"next": CURSOR}
    assert [span.span_id for span in spans] == ["span-3"]
    assert export.next == NEWER_CURSOR
    assert isinstance(export.next, str)


def test_open_export_reports_nothing_newer_and_keeps_the_cursor(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        EXPORT,
        status=204,
        headers={INTROSPECTION_NEXT_HEADER: CURSOR},
    )

    with _conversations(fake_api).open_export("conv-1", next=CURSOR) as export:
        spans = list(export.iter_spans())
        raw = b"".join(export.iter_bytes())

    assert export.nothing_newer is True
    assert export.status_code == 204
    assert export.next == CURSOR
    assert spans == []
    assert raw == b""


def test_open_export_without_the_header_has_no_cursor(fake_api: FakeAPI):
    """A newest-first export answers no `Introspection-Next`."""
    fake_api.add("GET", EXPORT, content=jsonl_body("span-1"))

    with _conversations(fake_api).open_export("conv-1") as export:
        assert export.next is None
        assert export.nothing_newer is False
        assert len(list(export.iter_spans())) == 1

    assert "direction" not in fake_api.last_request.params
    assert "next" not in fake_api.last_request.params


def test_open_export_streams_other_formats_as_bytes(fake_api: FakeAPI):
    body = b'[{"role": "meta"}]'
    fake_api.add(
        "GET",
        EXPORT,
        content=body,
        headers={INTROSPECTION_NEXT_HEADER: CURSOR},
    )

    with _conversations(fake_api).open_export(
        "conv-1", "trajectory", next=CURSOR
    ) as export:
        assert b"".join(export.iter_bytes()) == body
        with pytest.raises(ValueError, match="jsonl export"):
            next(iter(export.iter_spans()))

    assert export.next == CURSOR
    assert fake_api.last_request.headers["accept"] == (
        "application/vnd.letta.trajectory+json;version=1"
    )


def test_open_export_refusal_raises_on_entry(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        EXPORT,
        status=400,
        json_body={"detail": "next reads oldest-first; desc is refused"},
    )

    with (
        pytest.raises(IntrospectionAPIError) as error,
        _conversations(fake_api).open_export(
            "conv-1", direction="desc", next=CURSOR
        ),
    ):
        pytest.fail("the block must not run on an error status")

    assert error.value.status_code == 400
    assert dict(fake_api.last_request.params) == {
        "direction": "desc",
        "next": CURSOR,
    }


@pytest.mark.asyncio
async def test_async_open_export_resumes_and_reports_nothing_newer(
    fake_api: FakeAPI,
):
    conversations = AsyncConversations(fake_api.async_client())
    fake_api.add(
        "GET",
        EXPORT,
        content=jsonl_body("span-1"),
        headers={INTROSPECTION_NEXT_HEADER: CURSOR},
    )

    async with conversations.open_export("conv-1", direction="asc") as export:
        assert isinstance(export, AsyncConversationExport)
        assert export.next == CURSOR
        spans = [span async for span in export.iter_spans()]

    assert [span.span_id for span in spans] == ["span-1"]
    assert dict(fake_api.last_request.params) == {"direction": "asc"}

    fake_api.add(
        "GET",
        EXPORT,
        status=204,
        headers={INTROSPECTION_NEXT_HEADER: export.next},
    )
    async with conversations.open_export("conv-1", next=export.next) as again:
        chunks = [chunk async for chunk in again.iter_bytes()]

    assert again.nothing_newer is True
    assert again.next == CURSOR
    assert chunks == []
    assert fake_api.last_request.params["next"] == CURSOR


# --- items.list(direction=...) --------------------------------------


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_items_list_sends_direction_on_every_page(
    fake_api: FakeAPI, direction: str
):
    pages = iter(
        [
            {**make_page([make_item(span_id="span-1")], True), "next": CURSOR},
            make_page([make_item(span_id="span-2")], False),
        ]
    )
    fake_api.add_handler(
        "GET", ITEMS, lambda _request: httpx.Response(200, json=next(pages))
    )

    items = list(
        _conversations(fake_api).items.list(
            "conv-1",
            direction=direction,  # type: ignore[arg-type]
        )
    )

    assert [item.span_id for item in items] == ["span-1", "span-2"]
    first, second = fake_api.requests
    assert first.params["direction"] == direction
    assert "next" not in first.params
    # The token from a page is tied to its direction, so both go back.
    assert second.params["direction"] == direction
    assert second.params["next"] == CURSOR


def test_items_list_sends_no_direction_by_default(fake_api: FakeAPI):
    fake_api.add("GET", ITEMS, json_body=make_page([make_item()], False))

    list(_conversations(fake_api).items.list("conv-1"))

    assert "direction" not in fake_api.last_request.params


@pytest.mark.asyncio
async def test_async_items_list_sends_asc(fake_api: FakeAPI):
    fake_api.add("GET", ITEMS, json_body=make_page([make_item()], False))
    conversations = AsyncConversations(fake_api.async_client())

    items = [
        item
        async for item in conversations.items.list("conv-1", direction="asc")
    ]

    assert len(items) == 1
    assert fake_api.last_request.params["direction"] == "asc"
