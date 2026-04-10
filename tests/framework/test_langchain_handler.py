"""Tests for IntrospectionCallbackHandler (LangChain first-party handler)."""

from __future__ import annotations

import os
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

# LangChain is optional
HAS_LANGCHAIN = True
try:
    from langchain_openai import ChatOpenAI

    from introspection_sdk import IntrospectionCallbackHandler
except ImportError:
    HAS_LANGCHAIN = False
    if TYPE_CHECKING:
        from langchain_openai import ChatOpenAI

        from introspection_sdk import IntrospectionCallbackHandler

pytestmark = [
    pytest.mark.skipif(
        not HAS_LANGCHAIN,
        reason="langchain-openai not installed",
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
