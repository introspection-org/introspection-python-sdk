"""Arize Phoenix dual export integration tests.

Tests that Arize/OpenInference spans are received and converted by IntrospectionSpanProcessor.
"""

import os
from pathlib import Path

import openai
import pytest
from dirty_equals import IsInt, IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot

from .conftest import (
    HAS_ARIZE,
    HAS_OPENINFERENCE,
    HAS_OPENINFERENCE_ANTHROPIC,
    CaptureOpenInferenceSpans,
)

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_ARIZE or not HAS_OPENINFERENCE,
        reason="Arize/OpenInference dependencies not installed. Install with: uv sync --group arize",
    ),
]

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "test_arize"
_DUMMY_KEY_PREFIX = "sk-ant-test-dummy"


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


@pytest.mark.skipif(
    not HAS_OPENINFERENCE_ANTHROPIC,
    reason="openinference-instrumentation-anthropic not installed.",
)
def test_arize_anthropic_messages_dual_export(
    arize_anthropic_provider: CaptureOpenInferenceSpans,
    anthropic_model: str,
    request: pytest.FixtureRequest,
):
    """Anthropic messages -> Arize + Introspection via OpenInference."""
    import anthropic

    cassette = _CASSETTE_DIR / f"{request.node.name}.yaml"
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not cassette.exists() and (
        not key or key.startswith(_DUMMY_KEY_PREFIX)
    ):
        pytest.skip(
            f"No cassette at {cassette.name} and ANTHROPIC_API_KEY "
            "missing/dummy; record with --record-mode=once. See "
            "docs/test-quality-audit-plan.md (Phase 3c)."
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=anthropic_model,
        max_tokens=64,
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    assert response.content
    assert response.content[0].type == "text"

    arize_anthropic_provider.processor.force_flush()
    spans = arize_anthropic_provider.exporter.get_finished_spans()
    chat_spans = [
        s for s in spans if s["attributes"].get("gen_ai.system") == "anthropic"
    ]
    assert chat_spans, (
        "expected anthropic span; got "
        f"{[s['attributes'].get('gen_ai.system') for s in spans]}"
    )
    assert chat_spans[0]["attributes"] == IsPartialDict(
        {
            "gen_ai.system": "anthropic",
            "gen_ai.request.model": IsStr(),
            "gen_ai.response.id": IsStr(),
            "gen_ai.usage.input_tokens": IsInt(),
            "gen_ai.usage.output_tokens": IsInt(),
        }
    )
