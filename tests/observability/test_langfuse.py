"""Langfuse dual export integration tests.

Tests that Langfuse spans are captured and converted by IntrospectionSpanProcessor.
"""

import os

import logfire
import openai
import pytest
from dirty_equals import IsInt, IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot

from .conftest import (
    HAS_LANGFUSE,
    HAS_OPENINFERENCE,
    CaptureOpenInferenceSpans,
)

logfire.configure(
    send_to_logfire="if-token-present",
    console=False,
)

pytestmark = pytest.mark.vcr()


@pytest.fixture
def langfuse_openai_async_client():
    """Create an async OpenAI client instrumented with Langfuse."""
    try:
        from langfuse.openai import AsyncOpenAI
    except ImportError:
        pytest.skip("Langfuse dependencies not installed")
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    logfire.instrument_openai(client)
    return client


@pytest.mark.skipif(
    not HAS_LANGFUSE,
    reason="Langfuse dependencies not installed. Install with: uv sync --group langfuse",
)
async def test_langfuse_openai_chat_completion(
    langfuse_openai_async_client, openai_model: str
):
    """Test OpenAI chat completions API with async client."""
    with logfire.span("langfuse openai chat completion"):
        response = await langfuse_openai_async_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        output = response.choices[0].message.content
        assert output is not None
        print(f"Async chat completion: {output}")


@pytest.mark.skipif(
    not HAS_LANGFUSE or not HAS_OPENINFERENCE,
    reason="Langfuse/OpenInference dependencies not installed. Install with: uv sync --group langfuse --group arize",
)
def test_langfuse_openai_chat_completion_dual_export(
    langfuse_provider: CaptureOpenInferenceSpans,
):
    """Test that OTel spans are captured and converted by IntrospectionSpanProcessor."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a given city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "The city name",
                        }
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-5-nano",
        messages=[
            {
                "role": "user",
                "content": "What is the weather in San Francisco?",
            }
        ],
        tools=tools,  # type: ignore[arg-type]
    )
    result = response.choices[0].message
    print(f"\nOpenAI Response: {result}")

    langfuse_provider.processor.force_flush()

    spans = langfuse_provider.exporter.get_finished_spans()
    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "ChatCompletion",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.request.model": IsStr(),
                            "gen_ai.system": "openai",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.usage.input_tokens": IsInt(),
                            "gen_ai.usage.output_tokens": IsInt(),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "type": "function",
                                        "name": "get_weather",
                                        "description": "Get weather for a given city.",
                                        "parameters": {
                                            "type": "object",
                                            "properties": {
                                                "city": {
                                                    "type": "string",
                                                    "description": "The city name",
                                                }
                                            },
                                            "required": ["city"],
                                        },
                                    }
                                ]
                            ),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "What is the weather in San Francisco?",
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
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "get_weather",
                                                "arguments": '{"city":"San Francisco"}',
                                            }
                                        ],
                                    }
                                ]
                            ),
                        }
                    ),
                }
            ),
        ]
    )
