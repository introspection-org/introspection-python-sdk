"""Tests for Anthropic extended thinking with AnthropicInstrumentor.

Records actual Anthropic API responses to validate that thinking blocks
(with content + signature) are correctly captured in gen_ai spans.

Uses AnthropicInstrumentor (not logfire/OpenInference) since those
drop thinking blocks from the response.
"""

import json
import re
from typing import Any

import anthropic
import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import Contains, IsInt, IsJson, IsPartialDict, IsStr
from testing import TestSpanExporter

from introspection_sdk.anthropic import AnthropicInstrumentor
from introspection_sdk.config import AdvancedOptions

pytestmark = pytest.mark.vcr()


@pytest.fixture
def cap_anthropic_processor(monkeypatch):
    """Set up AnthropicInstrumentor with test exporter."""
    import os

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setenv(
        "ANTHROPIC_API_KEY",
        os.environ.get(
            "ANTHROPIC_API_KEY", "sk-ant-test-dummy-key-for-vcr-replay"
        ),
    )

    exporter = TestSpanExporter()
    from introspection_sdk import IntrospectionSpanProcessor

    processor = IntrospectionSpanProcessor(
        token="test-token",
        advanced=AdvancedOptions(span_exporter=exporter),
    )

    provider = TracerProvider()
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    instrumentor = AnthropicInstrumentor()
    instrumentor.instrument(tracer_provider=provider)

    try:
        yield CaptureSpanProcessor(exporter=exporter, processor=processor)
    finally:
        instrumentor.uninstrument()
        processor.shutdown()


async def test_anthropic_thinking_basic(
    cap_anthropic_processor: CaptureSpanProcessor,
):
    """Non-streaming: thinking block with content + signature."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        messages=[
            {"role": "user", "content": "What is 2+2? Think step by step."}
        ],
    )

    assert len(response.content) >= 2
    thinking_blocks = [b for b in response.content if b.type == "thinking"]
    text_blocks = [b for b in response.content if b.type == "text"]
    assert len(thinking_blocks) >= 1
    assert len(text_blocks) >= 1

    cap_anthropic_processor.processor.force_flush()
    spans = cap_anthropic_processor.exporter.get_finished_spans()

    assert len(spans) >= 1
    span = spans[0]

    assert span == IsPartialDict(
        {
            "name": "chat",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system": "anthropic",
                    "gen_ai.provider.name": "anthropic",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": "claude-sonnet-4-5-20250929",
                    "gen_ai.response.id": IsStr(),
                    "gen_ai.response.model": IsStr(),
                    "gen_ai.usage.input_tokens": IsInt(),
                    "gen_ai.usage.output_tokens": IsInt(),
                    "openinference.span.kind": "LLM",
                    "gen_ai.output.messages": IsJson(
                        [
                            IsPartialDict(
                                {
                                    "role": "assistant",
                                    "finish_reason": "stop",
                                    "parts": Contains(
                                        IsPartialDict(
                                            {
                                                "type": "thinking",
                                                "content": IsStr(),
                                                "signature": IsStr(),
                                                "provider_name": "anthropic",
                                            }
                                        )
                                    ),
                                }
                            )
                        ]
                    ),
                }
            ),
        }
    )


async def test_anthropic_thinking_multi_turn(
    cap_anthropic_processor: CaptureSpanProcessor,
):
    """Multi-turn: tool call returns 25°C, follow-up asks for Fahrenheit conversion.

    The model must reason over its previous output to convert the temperature.
    Validates thinking blocks in spans and that the answer is correct (within 2°F).
    """
    client = anthropic.Anthropic()
    tools: list[Any] = [
        {
            "name": "get_weather",
            "description": "Get weather for a city. Returns conditions and temperature in Celsius.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]

    messages: list[Any] = [
        {"role": "user", "content": "What is the weather in Tokyo?"}
    ]

    # Turn 1: thinking + tool call
    response1 = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        tools=tools,
        messages=messages,
    )

    tool_use_blocks = [b for b in response1.content if b.type == "tool_use"]
    assert len(tool_use_blocks) >= 1

    messages.append({"role": "assistant", "content": response1.content})
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": getattr(tool_use_blocks[0], "id", ""),
                    "content": "Clear, 25°C",
                }
            ],
        }
    )

    # Turn 2: model summarizes tool result
    response2 = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        tools=tools,
        messages=messages,
    )

    text_blocks = [b for b in response2.content if b.type == "text"]
    assert len(text_blocks) >= 1

    messages.append({"role": "assistant", "content": response2.content})
    messages.append(
        {
            "role": "user",
            "content": "What is that temperature in Fahrenheit?",
        }
    )

    # Turn 3: model reasons over previous output to convert 25°C → ~77°F
    response3 = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        messages=messages,
    )

    text_blocks3 = [b for b in response3.content if b.type == "text"]
    assert len(text_blocks3) >= 1

    # Verify the model's answer is close to 77°F (25°C = 77°F)
    answer_text = getattr(text_blocks3[0], "text", "")
    fahrenheit_match = re.search(r"(\d+(?:\.\d+)?)\s*°?F", answer_text)
    assert fahrenheit_match, (
        f"Expected Fahrenheit value in response: {answer_text}"
    )
    fahrenheit_value = float(fahrenheit_match.group(1))
    assert abs(fahrenheit_value - 77.0) <= 2.0, (
        f"Expected ~77°F, got {fahrenheit_value}°F"
    )

    cap_anthropic_processor.processor.force_flush()
    spans = cap_anthropic_processor.exporter.get_finished_spans()

    # Should have 3 spans
    assert len(spans) >= 3

    # Turn 1: output should have thinking + tool_call
    turn1_output = spans[0]["attributes"]["gen_ai.output.messages"]
    assert turn1_output == IsJson(
        [
            IsPartialDict(
                {
                    "role": "assistant",
                    "finish_reason": "tool-calls",
                    "parts": Contains(
                        IsPartialDict(
                            {"type": "thinking", "signature": IsStr()}
                        )
                    ),
                }
            )
        ]
    )

    # Turn 2: input should contain thinking blocks from history
    turn2_input = spans[1]["attributes"]["gen_ai.input.messages"]
    turn2_input_parsed = json.loads(turn2_input)
    assistant_parts = []
    for msg in turn2_input_parsed:
        if msg.get("role") == "assistant":
            assistant_parts.extend(msg.get("parts", []))
    thinking_in_history = [
        p for p in assistant_parts if p.get("type") == "thinking"
    ]
    assert len(thinking_in_history) >= 1, (
        "Thinking blocks should be in Turn 2 input history"
    )

    # Turn 3: output should have thinking (model reasoning about conversion)
    turn3_output = spans[2]["attributes"]["gen_ai.output.messages"]
    assert turn3_output == IsJson(
        [
            IsPartialDict(
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": Contains(IsPartialDict({"type": "thinking"})),
                }
            )
        ]
    )


async def test_anthropic_thinking_streaming(
    cap_anthropic_processor: CaptureSpanProcessor,
):
    """Streaming: thinking blocks accumulated and captured from streamed response."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        stream=True,
        thinking={"type": "enabled", "budget_tokens": 5000},
        messages=[{"role": "user", "content": "What is 3+3?"}],
    )

    # Consume the stream
    chunks = list(response)
    assert len(chunks) > 0

    cap_anthropic_processor.processor.force_flush()
    spans = cap_anthropic_processor.exporter.get_finished_spans()

    assert len(spans) >= 1
    span = spans[0]

    assert span == IsPartialDict(
        {
            "name": "chat",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system": "anthropic",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.response.id": IsStr(),
                    "gen_ai.usage.input_tokens": IsInt(),
                    "gen_ai.usage.output_tokens": IsInt(),
                    "gen_ai.output.messages": IsJson(
                        [
                            IsPartialDict(
                                {
                                    "role": "assistant",
                                    "finish_reason": "stop",
                                    "parts": Contains(
                                        IsPartialDict(
                                            {
                                                "type": "thinking",
                                                "content": IsStr(),
                                                "signature": IsStr(),
                                                "provider_name": "anthropic",
                                            }
                                        )
                                    ),
                                }
                            )
                        ]
                    ),
                    "openinference.span.kind": "LLM",
                }
            ),
        }
    )
