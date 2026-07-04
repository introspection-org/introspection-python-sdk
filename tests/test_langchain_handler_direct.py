"""Direct-drive tests for :class:`IntrospectionCallbackHandler`.

The existing ``tests/framework/test_langchain_handler.py`` exercises one
happy path through a real ``ChatOpenAI`` model over a VCR cassette. This
module covers the tool / chain / error / non-chat / hierarchy branches and
the private helpers by invoking the handler's real callback methods with
real LangChain message and result objects and a real in-memory span
exporter — no models, no network, no mocks.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import (
    ChatGeneration,
    Generation,
    LLMResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from introspection_sdk import AdvancedOptions
from introspection_sdk.otel.processors.langchain_callback_handler import (
    IntrospectionCallbackHandler,
)

# ``langchain-core`` is a pinned dependency of the ``test`` extra, so it
# is imported unconditionally here rather than guarded with
# ``importorskip``. A silent skip would hide this coverage in any env
# that forgot the extra (and violates the AGENTS "no skip without a
# linked issue" rule); a missing import should fail loudly instead.


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def handler(
    exporter: InMemorySpanExporter,
) -> IntrospectionCallbackHandler:
    return IntrospectionCallbackHandler(
        advanced=AdvancedOptions(span_exporter=exporter)
    )


def _spans(exporter: InMemorySpanExporter):
    return list(exporter.get_finished_spans())


def _attrs(span) -> dict:
    return dict(span.attributes or {})


# --- chat model happy path ------------------------------------------


def test_chat_model_start_and_end(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]},
        [[SystemMessage(content="Be brief"), HumanMessage(content="Hi")]],
        run_id=run_id,
        kwargs={},
        invocation_params={"model": "gpt-4o"},
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="Hello"))]],
            llm_output={
                "model_name": "gpt-4o",
                "id": "resp_1",
                "token_usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                },
            },
        ),
        run_id=run_id,
    )

    (span,) = _spans(exporter)
    attrs = _attrs(span)
    assert span.name == "chat gpt-4o"
    assert attrs["gen_ai.operation.name"] == "chat"
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["gen_ai.request.model"] == "gpt-4o"
    assert attrs["gen_ai.system"] == "ChatOpenAI"
    assert "Hi" in attrs["gen_ai.input.messages"]
    assert "Be brief" in attrs["gen_ai.system_instructions"]
    assert "Hello" in attrs["gen_ai.output.messages"]
    assert attrs["gen_ai.usage.input_tokens"] == 5
    assert attrs["gen_ai.usage.output_tokens"] == 2
    assert attrs["gen_ai.response.model"] == "gpt-4o"
    assert attrs["gen_ai.response.id"] == "resp_1"


def test_openrouter_usage_cost_attributes(handler, exporter):
    """OpenRouter-style usage.cost fields land as span attributes."""
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]},
        [[HumanMessage(content="Hi")]],
        run_id=run_id,
        kwargs={},
        invocation_params={"model": "openrouter/model"},
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="Hey"))]],
            llm_output={
                "model_name": "openrouter/model",
                "id": "resp_cost",
                "token_usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "cost": 0.95,
                    "cost_details": {"upstream_inference_cost": 0.5},
                    "completion_tokens_details": {"reasoning_tokens": 128},
                },
            },
        ),
        run_id=run_id,
    )

    (span,) = _spans(exporter)
    attrs = _attrs(span)
    assert attrs["gen_ai.usage.input_tokens"] == 5
    assert attrs["gen_ai.usage.output_tokens"] == 2
    assert attrs["introspection.llm.cost_usd"] == 0.95
    assert attrs["introspection.llm.upstream_cost_usd"] == 0.5
    assert attrs["gen_ai.usage.reasoning_tokens"] == 128


def test_usage_without_cost_emits_no_cost_attributes(handler, exporter):
    """Absent or malformed cost fields emit no cost attributes."""
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]},
        [[HumanMessage(content="Hi")]],
        run_id=run_id,
        kwargs={},
        invocation_params={"model": "gpt-4o"},
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="Hey"))]],
            llm_output={
                "model_name": "gpt-4o",
                "id": "resp_nocost",
                "token_usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    # Malformed: non-numeric cost must be skipped, not raised.
                    "cost": "not-a-number",
                    "completion_tokens_details": {"reasoning_tokens": "many"},
                },
            },
        ),
        run_id=run_id,
    )

    (span,) = _spans(exporter)
    attrs = _attrs(span)
    assert "introspection.llm.cost_usd" not in attrs
    assert "introspection.llm.upstream_cost_usd" not in attrs
    assert "gen_ai.usage.reasoning_tokens" not in attrs


def test_chat_with_tools_and_temperature(handler, exporter):
    run_id = uuid.uuid4()
    tool_def = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object"},
        },
    }
    handler.on_chat_model_start(
        {"id": ["x"]},
        [[HumanMessage(content="weather?")]],
        run_id=run_id,
        invocation_params={
            "model": "gpt-4o",
            "tools": [tool_def],
            "temperature": 0.7,
        },
    )
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_weather",
                "args": {"city": "SF"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    handler.on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=ai)]]),
        run_id=run_id,
    )

    attrs = _attrs(_spans(exporter)[0])
    assert "get_weather" in attrs["gen_ai.tool.definitions"]
    assert attrs["gen_ai.request.temperature"] == 0.7
    assert "get_weather" in attrs["gen_ai.output.messages"]
    # response.id falls back to the run id when the provider gives none.
    assert attrs["gen_ai.response.id"] == f"langchain-{run_id}"


def test_response_id_falls_back_to_system_fingerprint(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {}, [[HumanMessage(content="hi")]], run_id=run_id
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="ok"))]],
            llm_output={"system_fingerprint": "fp_abc"},
        ),
        run_id=run_id,
    )
    assert _attrs(_spans(exporter)[0])["gen_ai.response.id"] == "fp_abc"


# --- non-chat llm fallback ------------------------------------------


def test_on_llm_start_fallback(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_llm_start(
        {"kwargs": {"model_name": "text-model"}},
        ["prompt one", "prompt two"],
        run_id=run_id,
    )
    handler.on_llm_end(
        LLMResult(generations=[[Generation(text="answer")]]),
        run_id=run_id,
    )
    attrs = _attrs(_spans(exporter)[0])
    assert attrs["gen_ai.request.model"] == "text-model"
    assert "prompt one" in attrs["gen_ai.input.messages"]
    assert "answer" in attrs["gen_ai.output.messages"]


def test_on_llm_start_without_model_name(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_llm_start({}, ["p"], run_id=run_id)
    handler.on_llm_end(
        LLMResult(generations=[[Generation(text="a")]]), run_id=run_id
    )
    assert _spans(exporter)[0].name == "llm"


def test_on_llm_end_unknown_run_id_is_noop(handler, exporter):
    handler.on_llm_end(LLMResult(generations=[]), run_id=uuid.uuid4())
    assert _spans(exporter) == []


def test_on_llm_error_sets_error_status(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {}, [[HumanMessage(content="hi")]], run_id=run_id
    )
    handler.on_llm_error(ValueError("boom"), run_id=run_id)
    span = _spans(exporter)[0]
    assert span.status.status_code == StatusCode.ERROR
    assert _attrs(span)["exception.message"] == "boom"


def test_on_llm_error_unknown_run_id_is_noop(handler, exporter):
    handler.on_llm_error(ValueError("x"), run_id=uuid.uuid4())
    assert _spans(exporter) == []


# --- chains ----------------------------------------------------------


def test_chain_start_end(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start({"name": "my-chain"}, {}, run_id=run_id)
    handler.on_chain_end({"result": 1}, run_id=run_id)
    span = _spans(exporter)[0]
    assert span.name == "my-chain"
    assert "gen_ai.conversation.id" in _attrs(span)


def test_chain_name_from_serialized_id(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start({"id": ["pkg", "MyRunnable"]}, {}, run_id=run_id)
    handler.on_chain_end({}, run_id=run_id)
    assert _spans(exporter)[0].name == "MyRunnable"


def test_chain_error(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start({"name": "c"}, {}, run_id=run_id)
    handler.on_chain_error(RuntimeError("bad"), run_id=run_id)
    span = _spans(exporter)[0]
    assert span.status.status_code == StatusCode.ERROR


def test_chain_end_unknown_run_id_is_noop(handler, exporter):
    handler.on_chain_end({}, run_id=uuid.uuid4())
    assert _spans(exporter) == []


# --- tools -----------------------------------------------------------


def test_tool_start_end_string_output(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_tool_start({"name": "search"}, "query", run_id=run_id)
    handler.on_tool_end("result text", run_id=run_id)
    attrs = _attrs(_spans(exporter)[0])
    assert attrs["gen_ai.tool.name"] == "search"
    assert attrs["openinference.span.kind"] == "TOOL"
    assert attrs["gen_ai.tool.input"] == "query"
    assert attrs["gen_ai.tool.output"] == "result text"


def test_tool_end_object_with_content(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_tool_start({"name": "t"}, "in", run_id=run_id)
    handler.on_tool_end(
        ToolMessage(content="from content", tool_call_id="c1"),
        run_id=run_id,
    )
    assert _attrs(_spans(exporter)[0])["gen_ai.tool.output"] == "from content"


def test_tool_end_dict_output_is_stringified(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_tool_start({"name": "t"}, "in", run_id=run_id)
    handler.on_tool_end({"k": "v"}, run_id=run_id)
    # A bare dict has no ``.content``; the handler falls back to ``str()``.
    assert _attrs(_spans(exporter)[0])["gen_ai.tool.output"] == "{'k': 'v'}"


def test_tool_error(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_tool_start({"name": "t"}, "in", run_id=run_id)
    handler.on_tool_error(KeyError("nope"), run_id=run_id)
    assert _spans(exporter)[0].status.status_code == StatusCode.ERROR


def test_tool_end_unknown_run_id_is_noop(handler, exporter):
    handler.on_tool_end("x", run_id=uuid.uuid4())
    assert _spans(exporter) == []


# --- message conversion edge cases ----------------------------------


def test_tool_message_becomes_response_part(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {},
        [[ToolMessage(content="42", tool_call_id="call_9")]],
        run_id=run_id,
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="ok"))]]
        ),
        run_id=run_id,
    )
    msgs = _attrs(_spans(exporter)[0])["gen_ai.input.messages"]
    assert "tool_call_response" in msgs
    assert "call_9" in msgs


def test_list_content_text_parts(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chat_model_start(
        {},
        [[HumanMessage(content=[{"type": "text", "text": "part-a"}])]],
        run_id=run_id,
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="x"))]]
        ),
        run_id=run_id,
    )
    assert "part-a" in _attrs(_spans(exporter)[0])["gen_ai.input.messages"]


# --- hierarchy / agent name walk ------------------------------------


def test_child_span_inherits_agent_name(handler, exporter):
    root = uuid.uuid4()
    child = uuid.uuid4()
    handler.on_chain_start({"name": "planner-agent"}, {}, run_id=root)
    handler.on_chat_model_start(
        {},
        [[HumanMessage(content="hi")]],
        run_id=child,
        parent_run_id=root,
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="x"))]]
        ),
        run_id=child,
    )
    handler.on_chain_end({}, run_id=root)
    child_span = next(s for s in _spans(exporter) if s.name.startswith("chat"))
    assert _attrs(child_span)["gen_ai.agent.name"] == "planner-agent"


def test_wrapper_parent_name_is_skipped(handler, exporter):
    root = uuid.uuid4()
    child = uuid.uuid4()
    handler.on_chain_start({"name": "RunnableSequence"}, {}, run_id=root)
    handler.on_chat_model_start(
        {},
        [[HumanMessage(content="hi")]],
        run_id=child,
        parent_run_id=root,
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="x"))]]
        ),
        run_id=child,
    )
    handler.on_chain_end({}, run_id=root)
    child_span = next(s for s in _spans(exporter) if s.name.startswith("chat"))
    assert "gen_ai.agent.name" not in _attrs(child_span)


# --- conversation id resolution -------------------------------------


def test_conversation_id_from_metadata(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start(
        {"name": "c"},
        {},
        run_id=run_id,
        metadata={"gen_ai.conversation.id": "conv-explicit"},
    )
    handler.on_chain_end({}, run_id=run_id)
    assert (
        _attrs(_spans(exporter)[0])["gen_ai.conversation.id"]
        == "conv-explicit"
    )


def test_conversation_id_from_thread_id(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start(
        {"name": "c"}, {}, run_id=run_id, metadata={"thread_id": "thread-7"}
    )
    handler.on_chain_end({}, run_id=run_id)
    assert _attrs(_spans(exporter)[0])["gen_ai.conversation.id"] == "thread-7"


# --- helpers + lifecycle --------------------------------------------


def test_map_role_defaults_to_user(handler):
    assert handler._map_role("human") == "user"
    assert handler._map_role("ai") == "assistant"
    assert handler._map_role("unknown") == "user"


def test_normalize_tool_definition_flat_and_nested(handler):
    nested = handler._normalize_tool_definition(
        {"type": "function", "function": {"name": "f", "description": "d"}}
    )
    assert nested == {
        "type": "function",
        "name": "f",
        "description": "d",
        "parameters": None,
    }
    flat = handler._normalize_tool_definition({"name": "g"})
    assert flat["name"] == "g"


def test_shutdown_ends_open_spans(exporter):
    handler = IntrospectionCallbackHandler(
        advanced=AdvancedOptions(span_exporter=exporter)
    )
    run_id = uuid.uuid4()
    handler.on_chain_start({"name": "leaked"}, {}, run_id=run_id)
    # Span is still open; shutdown should flush it.
    handler.force_flush()
    handler.shutdown()
    assert any(s.name == "leaked" for s in _spans(exporter))
