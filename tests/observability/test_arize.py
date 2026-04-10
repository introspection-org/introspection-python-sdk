"""Arize Phoenix dual export integration tests.

Tests that Arize/OpenInference spans are received and converted by IntrospectionSpanProcessor.
"""

import openai
import pytest
from dirty_equals import IsInt, IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot

from .conftest import HAS_ARIZE, HAS_OPENINFERENCE, CaptureOpenInferenceSpans

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_ARIZE or not HAS_OPENINFERENCE,
        reason="Arize/OpenInference dependencies not installed. Install with: uv sync --group arize",
    ),
]


def test_arize_openai_chat_completion_dual_export(
    arize_provider: CaptureOpenInferenceSpans,
):
    """Test that Arize/OpenInference spans are converted to GenAI semconv."""
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

    arize_provider.processor.force_flush()

    spans = arize_provider.exporter.get_finished_spans()
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
