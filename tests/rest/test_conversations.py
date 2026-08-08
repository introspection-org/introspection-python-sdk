"""Contract tests for the read-only ``runner.conversations`` namespace.

Mirrors the JS SDK's ``tests/api/conversations.test.ts``: opaque cursor
pagination across both conversation envelopes, the
Responses-API-style ``retrieve()`` latest-turn heuristic, and the legacy
``tool_call_response`` ``result`` -> ``response`` normalization.

Driven through the offline :class:`FakeAPI` transport from
``conftest.py`` — nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import httpx
import pyarrow as pa
import pytest

from introspection_sdk.runner_resources import (
    AsyncConversations,
    Conversations,
)
from introspection_sdk.runner_resources._reads import ARROW_STREAM_MEDIA_TYPE
from introspection_sdk.schemas.conversations import Conversation
from introspection_sdk.schemas.genai import (
    TextPart,
    ToolCallResponsePart,
)
from introspection_sdk.schemas.genai_span import GenAiSpan
from introspection_sdk.schemas.trajectory import (
    TrajectoryAssistantRecord,
    TrajectoryMetaRecord,
)
from tests.schemas.test_genai_span import present

from .conftest import FakeAPI

RUNTIME_ID = "11111111-1111-1111-1111-111111111111"
RUNTIME_GROUP_ID = "22222222-2222-2222-2222-222222222222"
EXPERIMENT_ID = "33333333-3333-3333-3333-333333333333"

# --- Wire fixtures (raw dicts, as the DP returns them) --------------

SUMMARY_FIXTURE: dict[str, Any] = {
    "object": "conversation",
    "id": "conv-1",
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:05Z",
    "usage": {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    },
    "cost": {"usd": 0.01},
    "metrics": {
        "duration_ms": 5000,
        "trace_count": 1,
        "span_count": 3,
        "tool_use_count": 2,
        "failed_tool_use_count": 1,
        "has_errors": False,
    },
    "environment": "production",
    "service_name": "agent-runtime",
    "runtime_id": RUNTIME_ID,
    "experiment_id": EXPERIMENT_ID,
    "recipe_git_commit_sha": "abc123",
}

SUMMARY_WITH_AGENTS = {
    **SUMMARY_FIXTURE,
    "agents": [
        {"id": "root-run", "name": "agent", "depth": 0},
        {
            "id": "child-run",
            "name": "researcher",
            "parent_id": "root-run",
            "invocation_id": "child-invocation",
            "depth": 1,
        },
    ],
}


def make_item(**overrides: Any) -> dict[str, Any]:
    """A conversation item, as the DP returns it: a span.

    ``attributes`` is merged rather than replaced by overrides, so a test that
    sets one attribute does not silently drop the rest of the tree.
    """
    item: dict[str, Any] = {
        "trace_id": "trace-1",
        "span_id": "span-1",
        "start_time": "2025-01-01T00:00:00Z",
        "name": "chat anthropic",
        "kind": "CLIENT",
        "attributes": {"gen_ai": {"input": {"messages": []}}},
    }
    attributes = overrides.pop("attributes", None)
    item.update(overrides)
    if attributes is not None:
        gen_ai = {
            **item["attributes"].get("gen_ai", {}),
            **attributes.get("gen_ai", {}),
        }
        item["attributes"] = {
            **item["attributes"],
            **attributes,
            "gen_ai": gen_ai,
        }
    return item


def item_with_messages(
    *,
    span_id: str = "span-1",
    operation: str | None = None,
    input_messages: list[dict[str, Any]] | None = None,
    output_messages: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A span carrying messages, spelled the way the wire spells them."""
    gen_ai: dict[str, Any] = {}
    if operation is not None:
        gen_ai["operation"] = {"name": operation}
    gen_ai["input"] = {"messages": input_messages or []}
    if output_messages is not None:
        gen_ai["output"] = {"messages": output_messages}
    extra = overrides.pop("attributes", {})
    gen_ai.update(extra.get("gen_ai", {}))
    attributes = {**extra, "gen_ai": gen_ai}
    return make_item(span_id=span_id, attributes=attributes, **overrides)


def make_page(data: list[dict[str, Any]], has_more: bool) -> dict[str, Any]:
    return {
        "object": "list",
        "data": data,
        "first_id": data[0]["span_id"] if data else None,
        "last_id": data[-1]["span_id"] if data else None,
        "has_more": has_more,
        "next": "cursor-page-2" if has_more else None,
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

    page = convos.list(
        limit=10,
        conversation_id="conv-1",
        sort="tokens",
        direction="asc",
        model="claude-x",
        agent_name="agent",
        status="Error",
        service_name="agent-runtime",
        service_names=["agent-runtime", "worker"],
        environment="production",
        runtime_id=UUID(RUNTIME_ID),
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        experiment_id=UUID(EXPERIMENT_ID),
        recipe_git_commit_sha="abc123",
        start_date="2026-07-01T00:00:00Z",
        end_date="2026-07-02T00:00:00Z",
    )

    assert len(page.records) == 1
    assert page.records[0].agents is None
    req = fake_api.last_request
    assert req.path == "/v1/conversations"
    assert req.params.get("limit") == "10"
    assert req.params.get("conversation_id") == "conv-1"
    assert req.params.get("sort") == "tokens"
    assert req.params.get("direction") == "asc"
    assert req.params.get("model") == "claude-x"
    assert req.params.get("agent_name") == "agent"
    assert req.params.get("status") == "Error"
    assert req.params.get("environment") == "production"
    assert req.params.get("runtime_id") == RUNTIME_ID
    assert req.params.get("runtime_group_id") == RUNTIME_GROUP_ID
    assert req.params.get("experiment_id") == EXPERIMENT_ID
    assert req.params.get("recipe_git_commit_sha") == "abc123"
    assert req.params.get("start_date") == "2026-07-01T00:00:00Z"
    assert req.params.get("end_date") == "2026-07-02T00:00:00Z"
    assert req.url.params.get_list("service_names") == [
        "agent-runtime",
        "worker",
    ]

    summary = page.records[0]
    assert summary.id == "conv-1"
    assert summary.usage.total_tokens == 30
    assert summary.cost.usd == 0.01
    assert summary.metrics.tool_use_count == 2
    assert summary.metrics.failed_tool_use_count == 1


def test_get_returns_complete_agent_index(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1", json_body=SUMMARY_WITH_AGENTS
    )
    summary = _conversations(fake_api).get("conv-1")
    assert summary.agents is not None
    assert [
        (agent.id, agent.parent_id, agent.depth) for agent in summary.agents
    ] == [
        ("root-run", None, 0),
        ("child-run", "root-run", 1),
    ]


def test_the_span_declares_no_flattened_fields():
    # The flat envelope renamed a standard vocabulary into ~40 hand-named
    # columns. None of those names should exist on the span: an attribute is
    # addressed by its semantic-convention name, under `attributes`.
    fields = GenAiSpan.model_fields
    for flattened in (
        "response_model",
        "request_model",
        "operation_name",
        "model_name",
        "provider_name",
        "node_type",
        "input_tokens",
        "output_messages",
        "span_attributes",
        "introspection",
    ):
        assert flattened not in fields, flattened


async def test_async_list_uses_matching_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations",
        json_body=cursor_page([SUMMARY_FIXTURE], None),
    )
    convos = AsyncConversations(fake_api.async_client())

    page = await convos.list(
        conversation_id="conv-1",
        sort="cost",
        direction="desc",
        model="claude-x",
        environment="production",
        runtime_id=UUID(RUNTIME_ID),
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        experiment_id=UUID(EXPERIMENT_ID),
        recipe_git_commit_sha="abc123",
    )

    assert page.records[0].id == "conv-1"
    req = fake_api.last_request
    assert req.params.get("conversation_id") == "conv-1"
    assert req.params.get("sort") == "cost"
    assert req.params.get("direction") == "desc"
    assert req.params.get("model") == "claude-x"
    assert req.params.get("environment") == "production"
    assert req.params.get("runtime_id") == RUNTIME_ID
    assert req.params.get("runtime_group_id") == RUNTIME_GROUP_ID
    assert req.params.get("experiment_id") == EXPERIMENT_ID
    assert req.params.get("recipe_git_commit_sha") == "abc123"


def test_iter_drives_cursor_next_until_exhausted(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/conversations",
        _sequence_handler(
            [
                cursor_page([SUMMARY_FIXTURE], "cursor-2"),
                cursor_page([{**SUMMARY_FIXTURE, "id": "conv-2"}], None),
            ]
        ),
    )
    convos = _conversations(fake_api)

    summaries = list(convos.list())

    assert len(summaries) == 2
    assert summaries[1].id == "conv-2"
    assert len(fake_api.requests) == 2
    assert fake_api.requests[1].params.get("next") == "cursor-2"


# --- Arrow decode path ----------------------------------------------


def _arrow_stream(rows: list[dict[str, Any]]) -> bytes:
    table = pa.Table.from_pylist(rows)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def test_list_arrow_decodes_body_and_headers(fake_api: FakeAPI):
    body = _arrow_stream(
        [SUMMARY_FIXTURE, {**SUMMARY_FIXTURE, "id": "conv-2"}]
    )
    fake_api.add(
        "GET",
        "/v1/conversations",
        content=body,
        headers={
            "X-Next-Cursor": "cursor-2",
            "X-Result-Count": "2",
            "X-Total-Count": "9",
            "X-Truncated": "true",
        },
    )
    convos = _conversations(fake_api)

    page = convos.list(format="arrow").page()

    # Accept header negotiated the Arrow stream.
    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert [s.id for s in page.records] == ["conv-1", "conv-2"]
    assert isinstance(page.records[0], Conversation)
    assert page.records[0].usage.total_tokens == 30
    assert page.next == "cursor-2"
    assert page.count == 2
    assert page.total_count == 9


async def test_async_list_arrow_decodes_body_and_headers(fake_api: FakeAPI):
    body = _arrow_stream([SUMMARY_FIXTURE])
    fake_api.add(
        "GET",
        "/v1/conversations",
        content=body,
        headers={"X-Result-Count": "1", "X-Total-Count": "1"},
    )
    convos = AsyncConversations(fake_api.async_client())

    page = await convos.list(format="arrow").page()

    assert (
        fake_api.last_request.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    )
    assert [s.id for s in page.records] == ["conv-1"]
    assert page.count == 1
    assert page.total_count == 1
    assert page.next is None


# --- columnar .arrow() accessor -------------------------------------


def test_arrow_accessor_yields_tables_per_page(fake_api: FakeAPI):
    page1 = _arrow_stream(
        [SUMMARY_FIXTURE, {**SUMMARY_FIXTURE, "id": "conv-2"}]
    )
    page2 = _arrow_stream([{**SUMMARY_FIXTURE, "id": "conv-3"}])
    responses = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler(
        "GET", "/v1/conversations", lambda _req: next(responses)
    )
    convos = _conversations(fake_api)

    tables = list(convos.arrow(limit=2, environment="production"))

    assert [t.num_rows for t in tables] == [2, 1]
    assert all(isinstance(t, pa.Table) for t in tables)
    req = fake_api.requests[0]
    assert req.headers.get("accept") == ARROW_STREAM_MEDIA_TYPE
    assert req.params.get("environment") == "production"
    assert fake_api.requests[1].params.get("next") == "cursor-2"


def test_arrow_accessor_read_all_concatenates(fake_api: FakeAPI):
    page1 = _arrow_stream([SUMMARY_FIXTURE])
    page2 = _arrow_stream([{**SUMMARY_FIXTURE, "id": "conv-2"}])
    responses = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler(
        "GET", "/v1/conversations", lambda _req: next(responses)
    )
    convos = _conversations(fake_api)

    table = convos.arrow().read_all()

    assert isinstance(table, pa.Table)
    assert table.num_rows == 2
    assert table.column("id").to_pylist() == ["conv-1", "conv-2"]


async def test_async_arrow_accessor_read_all(fake_api: FakeAPI):
    page1 = _arrow_stream([SUMMARY_FIXTURE])
    page2 = _arrow_stream([{**SUMMARY_FIXTURE, "id": "conv-2"}])
    responses = iter(
        [
            httpx.Response(
                200, content=page1, headers={"X-Next-Cursor": "cursor-2"}
            ),
            httpx.Response(200, content=page2, headers={}),
        ]
    )
    fake_api.add_handler(
        "GET", "/v1/conversations", lambda _req: next(responses)
    )
    convos = AsyncConversations(fake_api.async_client())

    table = await convos.arrow().read_all()

    assert table.num_rows == 2
    assert table.column("id").to_pylist() == ["conv-1", "conv-2"]


# --- items.list()/iter() (opaque next paging) ---------------------


def test_items_list_passes_includes(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page([make_item()], False),
    )
    convos = _conversations(fake_api)

    page = convos.items.list(
        "conv-1",
        order="asc",
        include=[
            "gen_ai.system_instructions",
            "gen_ai.tool.definitions",
            "events",
            "span_attributes",
            "resource_attributes",
        ],
        agent="root",
    )

    assert len(page.data) == 1
    req = fake_api.last_request
    assert req.path == "/v1/conversations/conv-1/items"
    assert req.params.get("order") == "asc"
    assert _includes(req) == [
        "gen_ai.system_instructions",
        "gen_ai.tool.definitions",
        "events",
        "span_attributes",
        "resource_attributes",
    ]
    assert req.params.get("agent") == "root"
    assert req.params.get("agent_name") is None
    assert req.params.get("agent_id") is None


def test_items_iter_drives_next_cursor_while_has_more(fake_api: FakeAPI):
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
    assert fake_api.requests[0].params.get("next") is None
    assert fake_api.requests[1].params.get("next") == "cursor-page-2"


def test_items_iter_terminates_on_empty_page(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/items", json_body=make_page([], False)
    )
    convos = _conversations(fake_api)

    items = list(convos.items.list("conv-1"))

    assert items == []
    assert len(fake_api.requests) == 1


def test_items_iter_rejects_has_more_without_next(fake_api: FakeAPI):
    page = make_page([make_item(id="item-1")], True)
    page["next"] = None
    fake_api.add("GET", "/v1/conversations/conv-1/items", json_body=page)
    convos = _conversations(fake_api)

    with pytest.raises(ValueError, match="has_more without next"):
        list(convos.items.list("conv-1"))


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

    item = convos.items.get("conv-1", "item-1", include=["events"])

    assert item.span_id == "span-1"
    # The message-family includes are gone from the vocabulary: full history is
    # returned unconditionally, so there is nothing left for them to gate.
    assert _includes(fake_api.last_request) == ["events"]


# --- retrieve() -----------------------------------------------------


def test_retrieve_picks_latest_chat_turn(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [
                item_with_messages(span_id="span-3"),
                item_with_messages(span_id="span-2", operation="chat"),
                item_with_messages(span_id="span-1"),
            ],
            False,
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/span-2",
        json_body=item_with_messages(
            span_id="span-2",
            operation="chat",
            start_time="2025-01-01T00:00:02Z",
            input_messages=[
                {"role": "user", "parts": [{"type": "text", "content": "hi"}]}
            ],
            output_messages=[
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "content": "hello"}],
                    "finish_reason": "stop",
                }
            ],
        ),
    )
    convos = _conversations(fake_api)

    span = convos.retrieve("conv-1")

    assert span is not None
    # The scan hit the items list (order=desc) then the item detail.
    assert fake_api.requests[0].params.get("order") == "desc"
    detail_req = fake_api.requests[1]
    assert detail_req.path == "/v1/conversations/conv-1/items/span-2"
    # No `include` at all: the items read returns the full history by default,
    # so asking for the messages you already have is gone from the contract.
    assert _includes(detail_req) == []

    assert span.span_id == "span-2"
    assert len(span.input_messages) == 1
    assert len(span.output_messages) == 1
    out_part = span.output_messages[0].parts[0]
    assert isinstance(out_part, TextPart)
    assert out_part.content == "hello"


def test_retrieve_returns_the_span_itself(fake_api: FakeAPI):
    # There is no separate response object any more — the span already carries
    # the full history, so composing a second type from it would be copying
    # fields into different names.
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/span-7",
        json_body=item_with_messages(
            span_id="span-7",
            operation="chat",
            attributes={"gen_ai": {"response": {"id": "resp-7"}}},
        ),
    )
    convos = _conversations(fake_api)

    span = convos.retrieve("conv-1", "span-7")

    assert len(fake_api.requests) == 1
    assert (
        fake_api.last_request.path == "/v1/conversations/conv-1/items/span-7"
    )
    assert span is not None
    assert isinstance(span, GenAiSpan)
    assert span.span_id == "span-7"
    assert present(present(span.attributes.gen_ai).response).id == "resp-7"


def test_retrieve_falls_back_to_the_first_span_that_produced_output(
    fake_api: FakeAPI,
):
    # `node_type == "assistant"` used to be the primary match. It was a
    # precomputed UI tree hint with no semantic-convention equivalent and is
    # gone from the wire, so the fallback carries more weight now: a span that
    # produced output is a turn even when nothing labelled it one.
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [
                item_with_messages(span_id="span-2"),
                item_with_messages(
                    span_id="span-1",
                    output_messages=[{"role": "assistant", "parts": []}],
                ),
            ],
            False,
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/span-1",
        json_body=item_with_messages(
            span_id="span-1",
            output_messages=[{"role": "assistant", "parts": []}],
        ),
    )
    convos = _conversations(fake_api)

    span = convos.retrieve("conv-1")

    assert span is not None
    assert span.span_id == "span-1"


def test_retrieve_returns_none_when_no_items(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/items", json_body=make_page([], False)
    )
    convos = _conversations(fake_api)

    assert convos.retrieve("conv-1") is None
    assert len(fake_api.requests) == 1


def test_retrieve_maps_legacy_result_to_response(fake_api: FakeAPI):
    # The compat shim survives the envelope change: older DP deployments emit
    # `result` where semconv says `response`. Only the path to the messages
    # moved — the mapping itself is unchanged and still needed.
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items",
        json_body=make_page(
            [item_with_messages(span_id="span-1", operation="chat")], False
        ),
    )
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/items/span-1",
        json_body=item_with_messages(
            span_id="span-1",
            operation="chat",
            input_messages=[
                {
                    "role": "tool",
                    "parts": [
                        {
                            "type": "tool_call_response",
                            "id": "call-1",
                            "result": {"ok": True},
                        },
                        {"type": "text", "content": "unrelated"},
                    ],
                }
            ],
            output_messages=[
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

    span = convos.retrieve("conv-1")

    assert span is not None
    legacy = span.input_messages[0].parts[0]
    assert isinstance(legacy, ToolCallResponsePart)
    assert legacy.response == {"ok": True}
    # A part already in the semconv spelling passes through untouched.
    already = span.output_messages[0].parts[0]
    assert isinstance(already, ToolCallResponsePart)
    assert already.response == "already-semconv"
    # Non-tool parts are not rewritten.
    assert isinstance(span.input_messages[0].parts[1], TextPart)


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


# --- complete-conversation export -----------------------------------

TRAJECTORY_BODY = [
    {"role": "meta", "source": "claude-code", "model": "opus"},
    {
        "role": "user",
        "content": "fix the bug",
        "timestamp": "2025-01-01T00:00:00Z",
    },
    {
        "role": "assistant",
        "content": None,
        "timestamp": "2025-01-01T00:00:01Z",
        "tool_calls": [
            {"id": "call_1", "name": "edit", "args": '{"path": "a.py"}'}
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "ok",
        "timestamp": "2025-01-01T00:00:02Z",
        "ok": True,
    },
    {
        "role": "assistant",
        "content": "done",
        "timestamp": "2025-01-01T00:00:03Z",
    },
]


def test_export_trajectory_negotiates_v1_and_types_records(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/export", json_body=TRAJECTORY_BODY
    )
    records = _conversations(fake_api).export_trajectory("conv-1")

    sent = fake_api.requests[-1]
    # The version parameter is load-bearing: a server that does not implement
    # it must answer 406 rather than silently serving a different shape.
    assert sent.headers["accept"] == (
        "application/vnd.letta.trajectory+json;version=1"
    )

    assert [type(r).__name__ for r in records] == [
        "TrajectoryMetaRecord",
        "TrajectoryUserRecord",
        "TrajectoryAssistantRecord",
        "TrajectoryToolRecord",
        "TrajectoryAssistantRecord",
    ]
    tool_call_turn = records[2]
    assert isinstance(tool_call_turn, TrajectoryAssistantRecord)
    # `content: null` is what distinguishes a tool-call record from prose.
    assert tool_call_turn.content is None
    assert tool_call_turn.tool_calls is not None
    assert tool_call_turn.tool_calls[0].name == "edit"
    # args stays a JSON-encoded string — that is the upstream contract.
    assert tool_call_turn.tool_calls[0].args == '{"path": "a.py"}'

    prose_turn = records[4]
    assert isinstance(prose_turn, TrajectoryAssistantRecord)
    assert prose_turn.content == "done"
    assert prose_turn.tool_calls is None


def test_export_trajectory_sends_filters_but_no_pagination(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/export", json_body=TRAJECTORY_BODY
    )
    _conversations(fake_api).export_trajectory(
        "conv-1",
        agent="root",
        service_name="svc",
        operation_name="chat",
        lookback_days=7,
        share_id="33333333-3333-3333-3333-333333333333",
    )

    params = dict(fake_api.requests[-1].params)
    assert params == {
        "agent": "root",
        "service_name": "svc",
        "operation_name": "chat",
        "lookback_days": "7",
        "share_id": "33333333-3333-3333-3333-333333333333",
    }
    # The export is assembled server-side over the whole conversation, so it
    # must never carry a cursor or page bound.
    assert "limit" not in params
    assert "next" not in params


def test_export_arrow_negotiates_arrow_and_returns_one_table(
    fake_api: FakeAPI,
):
    table = pa.table({"id": ["a", "b"], "content": ["hi", "there"]})
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)

    fake_api.add(
        "GET", "/v1/conversations/conv-1/export", content=sink.getvalue()
    )
    result = _conversations(fake_api).export_arrow("conv-1")

    assert fake_api.requests[-1].headers["accept"] == ARROW_STREAM_MEDIA_TYPE
    assert result.num_rows == 2
    assert result.column("content").to_pylist() == ["hi", "there"]


def test_export_arrow_empty_body_is_none(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/conversations/conv-1/export", content=b"")
    assert _conversations(fake_api).export_arrow("conv-1") is None


@pytest.mark.asyncio
async def test_async_export_trajectory(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/conversations/conv-1/export", json_body=TRAJECTORY_BODY
    )
    conversations = AsyncConversations(fake_api.async_client())
    records = await conversations.export_trajectory("conv-1")
    assert len(records) == 5
    meta = records[0]
    assert isinstance(meta, TrajectoryMetaRecord)
    assert meta.source == "claude-code"
