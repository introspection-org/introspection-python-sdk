"""Tests for IntrospectionCallbackHandler (LangChain first-party handler)."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest
from dirty_equals import IsJson, IsPositiveInt, IsStr
from inline_snapshot import snapshot
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from introspection_sdk import AdvancedOptions
from tests.test_utils import (
    IncrementalIdGenerator,
    TimeGenerator,
    spans_to_dict,
)

# LangChain integrations are optional.
HAS_LANGCHAIN_HANDLER = True
HAS_LANGCHAIN_OPENAI = True
try:
    from introspection_sdk import IntrospectionCallbackHandler
    from introspection_sdk.processors.langchain_callback_handler import (
        HAS_LANGCHAIN,
    )
except ImportError:
    HAS_LANGCHAIN_HANDLER = False
    if TYPE_CHECKING:
        from introspection_sdk import IntrospectionCallbackHandler
else:
    HAS_LANGCHAIN_HANDLER = HAS_LANGCHAIN
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    HAS_LANGCHAIN_OPENAI = False
    if TYPE_CHECKING:
        from langchain_openai import ChatOpenAI

pytestmark = [
    pytest.mark.skipif(
        not HAS_LANGCHAIN_HANDLER,
        reason="langchain-core not installed",
    ),
    pytest.mark.vcr(),
]

DUMMY_OPENAI_KEY = "sk-test-dummy-key-for-vcr-replay"

# Matches auto-generated conversation IDs
_CONV_ID = IsStr(regex=r"^intro_conv_[0-9a-f]{32}$")


@pytest.fixture(autouse=True)
def _set_openai_key(monkeypatch):
    """Set dummy OpenAI key for VCR replay."""
    monkeypatch.setenv(
        "OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", DUMMY_OPENAI_KEY)
    )


class TestIntrospectionCallbackHandler:
    """Test suite for IntrospectionCallbackHandler."""

    @pytest.mark.skipif(
        not HAS_LANGCHAIN_OPENAI,
        reason="langchain-openai not installed",
    )
    def test_chat_completion_with_gen_ai_attributes(self):
        """Test that LangChain chat completion produces correct gen_ai spans."""
        exporter = InMemorySpanExporter()

        handler = IntrospectionCallbackHandler(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        model = ChatOpenAI(model="gpt-5-nano")
        response = model.invoke(
            "Say hello in one word.",
            config={"callbacks": [handler]},
        )

        assert response.content
        assert len(response.content) > 0

        handler.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        spans = sorted(spans, key=lambda s: s["start_time"])

        assert spans == snapshot(
            [
                {
                    "name": "chat gpt-5-nano",
                    "context": {
                        "trace_id": 1,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "parent": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "start_time": IsPositiveInt,
                    "end_time": IsPositiveInt,
                    "attributes": {
                        "gen_ai.operation.name": "chat",
                        "gen_ai.conversation.id": _CONV_ID,
                        "openinference.span.kind": "LLM",
                        "gen_ai.request.model": "gpt-5-nano",
                        "gen_ai.system": "ChatOpenAI",
                        "gen_ai.input.messages": IsJson(
                            [
                                {
                                    "role": "user",
                                    "parts": [
                                        {
                                            "type": "text",
                                            "content": "Say hello in one word.",
                                        }
                                    ],
                                }
                            ]
                        ),
                        "gen_ai.output.messages": IsJson(
                            [
                                {
                                    "role": "assistant",
                                    "parts": [
                                        {
                                            "type": "text",
                                            "content": IsStr(),
                                        }
                                    ],
                                }
                            ]
                        ),
                        "gen_ai.usage.input_tokens": IsPositiveInt,
                        "gen_ai.usage.output_tokens": IsPositiveInt,
                        "gen_ai.response.model": IsStr(),
                        "gen_ai.response.id": IsStr(),
                    },
                },
            ]
        )

        handler.shutdown()

    def test_thread_id_metadata_maps_to_conversation_id(self):
        """LangGraph thread_id metadata is used as gen_ai.conversation.id."""
        exporter = InMemorySpanExporter()
        handler = IntrospectionCallbackHandler(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        run_id = uuid.uuid4()
        handler.on_chain_start(
            {"name": "LangGraph"},
            {"input": "hello"},
            run_id=run_id,
            metadata={"thread_id": "thread-123"},
        )
        handler.on_chain_end({"output": "hello!"}, run_id=run_id)
        handler.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        assert spans[0]["attributes"]["gen_ai.conversation.id"] == "thread-123"

        handler.shutdown()

    def test_explicit_conversation_id_takes_precedence_over_thread_id(self):
        """Explicit GenAI conversation metadata wins over framework thread metadata."""
        exporter = InMemorySpanExporter()
        handler = IntrospectionCallbackHandler(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        run_id = uuid.uuid4()
        handler.on_chain_start(
            {"name": "LangGraph"},
            {"input": "hello"},
            run_id=run_id,
            metadata={
                "thread_id": "thread-123",
                "gen_ai.conversation.id": "conversation-456",
            },
        )
        handler.on_chain_end({"output": "hello!"}, run_id=run_id)
        handler.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        assert (
            spans[0]["attributes"]["gen_ai.conversation.id"]
            == "conversation-456"
        )

        handler.shutdown()

    def test_independent_top_level_runs_have_distinct_traces(self):
        """A shared handler must not merge independent top-level runs."""
        exporter = InMemorySpanExporter()
        handler = IntrospectionCallbackHandler(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        first_run_id = uuid.uuid4()
        second_run_id = uuid.uuid4()

        handler.on_chain_start(
            {"name": "LangGraph"},
            {"input": "first"},
            run_id=first_run_id,
            metadata={"thread_id": "email-1"},
        )
        handler.on_chain_start(
            {"name": "LangGraph"},
            {"input": "second"},
            run_id=second_run_id,
            metadata={"thread_id": "email-2"},
        )
        handler.on_chain_end({"output": "first"}, run_id=first_run_id)
        handler.on_chain_end({"output": "second"}, run_id=second_run_id)
        handler.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        traces_by_conversation = {
            span["attributes"]["gen_ai.conversation.id"]: span["context"][
                "trace_id"
            ]
            for span in spans
        }

        assert traces_by_conversation["email-1"] != traces_by_conversation["email-2"]

        handler.shutdown()

    def test_child_run_uses_parent_trace(self):
        """Nested callbacks stay under their top-level run's trace."""
        exporter = InMemorySpanExporter()
        handler = IntrospectionCallbackHandler(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        parent_run_id = uuid.uuid4()
        child_run_id = uuid.uuid4()

        handler.on_chain_start(
            {"name": "LangGraph"},
            {"input": "hello"},
            run_id=parent_run_id,
            metadata={"thread_id": "email-1"},
        )
        handler.on_tool_start(
            {"name": "lookup"},
            "input",
            run_id=child_run_id,
            parent_run_id=parent_run_id,
            metadata={"thread_id": "email-1"},
        )
        handler.on_tool_end("output", run_id=child_run_id)
        handler.on_chain_end({"output": "done"}, run_id=parent_run_id)
        handler.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        trace_ids = {span["context"]["trace_id"] for span in spans}

        assert len(trace_ids) == 1

        handler.shutdown()
