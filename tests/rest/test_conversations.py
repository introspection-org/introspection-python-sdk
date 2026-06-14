"""Contract tests for the read-only ``runner.conversations`` namespace.

Mirrors the JS SDK's ``tests/api/conversations.test.ts``: the two paging
protocols (cursor ``next`` vs OpenAI-style ``after``/``has_more``), the
Responses-API-style ``retrieve()`` latest-turn heuristic, and the legacy
``tool_call_response`` ``result`` -> ``response`` normalization.

Driven through the offline :class:`FakeAPI` transport from
``conftest.py`` — nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from introspection_sdk.runner_resources import Conversations
from introspection_sdk.schemas.genai import (
    TextPart,
    ToolCallResponsePart,
)

from .conftest import ORG_ID, PROJECT_ID, FakeAPI

# --- Wire fixtures (raw dicts, as the DP returns them) --------------

SUMMARY_FIXTURE: dict[str, Any] = {
    "trace_id": "trace-1",
    "conversation_id": "conv-1",
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "start_time": "2025-01-01T00:00:00Z",
    "end_time": "2025-01-01T00:00:05Z",
    "duration_ms": 5000,
    "total_input_tokens": 10,
    "total_output_tokens": 20,
    "trace_count": 1,
    "span_count": 3,
    "status": "Ok",
    "has_errors": False,
    "signal_categories": [],
    "input_messages": [],
    "output_messages": [],
}


def make_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "object": "conversation.item",
        "id": "item-1",
        "type": "span",
        "trace_id": "trace-1",
        "span_id": "span-1",
        "created_at": "2025-01-01T00:00:00Z",
        "span_name": "chat anthropic",
        "span_kind": "CLIENT",
        "node_type": "span",
        "input_messages": [],
    }
    item.update(overrides)
    return item


def make_page(data: list[dict[str, Any]], has_more: bool) -> dict[str, Any]:
    return {
        "object": "list",
        "data": data,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
        "has_more": has_more,
    }


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
    """Return successive JSON bodies on repeated calls to the same route."""
    it = iter(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(it))

    return handler


def _conversations(fake_api: FakeAPI) -> Conversations:
    return Conversations(fake_api.client())


def _includes(request: Any) -> list[str]:
    return [v for k, v in request.url.params.multi_items() if k == "include"]


# --- list() (cursor paging) ----------------------------------------


def test_list_calls_conversations_with_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations",
        json_body=cursor_page([SUMMARY_FIXTURE], None),
    )
    convos = _conversations(fake_api)

    page = convos.list(limit=10, status="Error")

    assert len(page.records) == 1
    req = fake_api.last_request
    assert req.path == "/v1/conversations"
    assert req.params.get("limit") == "10"
    assert req.params.get("status") == "Error"


def test_iter_drives_cursor_next_until_exhausted(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/conversations",
        _sequence_handler(
            [
                cursor_page([SUMMARY_FIXTURE], "cursor-2"),
                cursor_page(
                    [{**SUMMARY_FIXTURE, "trace_id": "trace-2"}], None
                ),
            ]
        ),
    )
    convos = _conversations(fake_api)

    summaries = list(convos.list())

    assert len(summaries) == 2
    assert summaries[1].trace_id == "trace-2"
    assert len(fake_api.requests) == 2
    assert fake_api.requests[1].params.get("next") == "cursor-2"


# --- items.list()/iter() (after/has_more paging) -------------------


def test_items_list_passes_includes(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page([make_item()], False),
    )
    convos = _conversations(fake_api)

    page = convos.items.list(
        "conv-1", order="asc", include=["events", "span_attributes"]
    )

    assert len(page.data) == 1
    req = fake_api.last_request
    assert req.path == "/v1/conversations/conv-1/items"
    assert req.params.get("order") == "asc"
    assert _includes(req) == ["events", "span_attributes"]


def test_items_iter_drives_after_while_has_more(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/conversations/conv-1/items",
        _sequence_handler(
            [
                make_page(
                    [make_item(id="item-1"), make_item(id="item-2")], True
                ),
                make_page([make_item(id="item-3")], False),
            ]
        ),
    )
    convos = _conversations(fake_api)

    items = list(convos.items.list("conv-1"))

    assert [i.id for i in items] == ["item-1", "item-2", "item-3"]
    assert len(fake_api.requests) == 2
    assert fake_api.requests[0].params.get("after") is None
    assert fake_api.requests[1].params.get("after") == "item-2"


def test_items_iter_terminates_on_empty_page(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/items", json_body=make_page([], False)
    )
    convos = _conversations(fake_api)

    items = list(convos.items.list("conv-1"))

    assert items == []
    assert len(fake_api.requests) == 1


def test_items_iter_walks_ascending_transcript(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/conversations/conv-1/items",
        _sequence_handler(
            [
                make_page([make_item(id="item-1")], True),
                make_page([make_item(id="item-2")], False),
            ]
        ),
    )
    convos = _conversations(fake_api)

    items = list(convos.items.list("conv-1", order="asc"))

    assert [i.id for i in items] == ["item-1", "item-2"]
    assert fake_api.requests[0].params.get("order") == "asc"
    assert fake_api.requests[1].params.get("order") == "asc"


def test_items_get_fetches_single_item(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/item-1",
        json_body=make_item(),
    )
    convos = _conversations(fake_api)

    item = convos.items.get(
        "conv-1", "item-1", include=["gen_ai.input.messages"]
    )

    assert item.id == "item-1"
    assert _includes(fake_api.last_request) == ["gen_ai.input.messages"]


# --- retrieve() -----------------------------------------------------


def test_retrieve_picks_latest_assistant_turn(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [
                make_item(id="item-3", node_type="tool_call"),
                make_item(id="item-2", node_type="assistant"),
                make_item(id="item-1", node_type="span"),
            ],
            False,
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/item-2",
        json_body=make_item(
            id="item-2",
            node_type="assistant",
            response_id="resp-2",
            model_name="claude-x",
            provider_name="anthropic",
            created_at="2025-01-01T00:00:02Z",
            input_messages=[
                {"role": "user", "parts": [{"type": "text", "content": "hi"}]}
            ],
            output_message={
                "role": "assistant",
                "parts": [{"type": "text", "content": "hello"}],
                "finish_reason": "stop",
            },
            system_instructions=[{"type": "text", "content": "be nice"}],
            tool_definitions=[{"name": "lookup"}],
        ),
    )
    convos = _conversations(fake_api)

    response = convos.retrieve("conv-1")

    assert response is not None
    # The scan hit the items list (order=desc) then the item detail.
    assert fake_api.requests[0].params.get("order") == "desc"
    detail_req = fake_api.requests[1]
    assert detail_req.path == "/v1/conversations/conv-1/items/item-2"
    assert _includes(detail_req) == [
        "gen_ai.input.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.definitions",
    ]
    assert response.item_id == "item-2"
    assert response.response_id == "resp-2"
    assert response.model == "claude-x"
    assert response.provider_name == "anthropic"
    assert len(response.input_messages) == 1
    # output_message is wrapped when gen_ai_output_messages is absent.
    assert len(response.output_messages) == 1
    out_part = response.output_messages[0].parts[0]
    assert isinstance(out_part, TextPart)
    assert out_part.content == "hello"
    assert response.system_instructions is not None
    assert response.system_instructions[0].content == "be nice"
    assert response.tool_definitions is not None
    assert response.tool_definitions[0].name == "lookup"


def test_retrieve_with_explicit_item_id_skips_scan(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/item-7",
        json_body=make_item(
            id="item-7", node_type="assistant", response_id="resp-7"
        ),
    )
    convos = _conversations(fake_api)

    response = convos.retrieve("conv-1", "item-7")

    assert len(fake_api.requests) == 1
    assert (
        fake_api.last_request.path == "/v1/conversations/conv-1/items/item-7"
    )
    assert response is not None
    assert response.item_id == "item-7"
    assert response.response_id == "resp-7"


def test_retrieve_falls_back_to_first_output_message(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [
                make_item(id="item-2", node_type="span"),
                make_item(
                    id="item-1",
                    node_type="span",
                    output_message={"role": "assistant", "parts": []},
                ),
            ],
            False,
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/item-1",
        json_body=make_item(
            id="item-1",
            output_message={"role": "assistant", "parts": []},
        ),
    )
    convos = _conversations(fake_api)

    response = convos.retrieve("conv-1")

    assert response is not None
    assert response.item_id == "item-1"


def test_retrieve_returns_none_when_no_items(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/items", json_body=make_page([], False)
    )
    convos = _conversations(fake_api)

    response = convos.retrieve("conv-1")

    assert response is None
    assert len(fake_api.requests) == 1


def test_retrieve_maps_legacy_result_to_response(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [make_item(id="item-1", node_type="assistant")], False
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/item-1",
        json_body=make_item(
            id="item-1",
            node_type="assistant",
            input_messages=[
                {
                    "role": "tool",
                    "parts": [
                        # Legacy DP shape: `result` instead of `response`.
                        {
                            "type": "tool_call_response",
                            "id": "call-1",
                            "result": {"ok": True},
                        },
                        {"type": "text", "content": "unrelated"},
                    ],
                }
            ],
            gen_ai_output_messages=[
                {
                    "role": "assistant",
                    "parts": [
                        {
                            "type": "tool_call_response",
                            "id": "call-2",
                            "response": "already-semconv",
                        }
                    ],
                }
            ],
        ),
    )
    convos = _conversations(fake_api)

    response = convos.retrieve("conv-1")

    assert response is not None
    part = response.input_messages[0].parts[0]
    assert isinstance(part, ToolCallResponsePart)
    assert part.id == "call-1"
    assert part.response == {"ok": True}
    # Non-tool parts pass through untouched.
    text_part = response.input_messages[0].parts[1]
    assert isinstance(text_part, TextPart)
    assert text_part.content == "unrelated"
    # gen_ai_output_messages is preferred over output_message.
    out_part = response.output_messages[0].parts[0]
    assert isinstance(out_part, ToolCallResponsePart)
    assert out_part.response == "already-semconv"


# --- Runner wiring --------------------------------------------------


def test_runner_exposes_conversations_namespace():
    from introspection_sdk._errors import RunnerExpiredError
    from introspection_sdk.runner import Runner

    from .conftest import runner_spec_payload

    spec = runner_spec_payload()
    runner = Runner(spec, refresher=lambda: spec)
    assert isinstance(runner.conversations, Conversations)
    runner.close()
    with pytest.raises(RunnerExpiredError):
        _ = runner.conversations
