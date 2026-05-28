"""Tests for Gemini thought signatures with GeminiInstrumentor.

Records actual ``google-genai`` API responses to validate that
``thought_signature`` (returned on text and function-call parts) is
correctly captured in gen_ai spans as ``ThinkingPart`` entries
(``content="[redacted]"`` when the signature is attached to a
non-thought part).

Uses ``GeminiInstrumentor`` (not logfire/OpenInference) since those
drop thought signatures from the response.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import Contains, IsInt, IsJson, IsPartialDict, IsStr
from google import genai
from google.genai import types
from testing import TestSpanExporter

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel.gemini import GeminiInstrumentor

pytestmark = pytest.mark.vcr()


GEMINI_MODEL = "gemini-3-pro-preview"


@pytest.fixture
def cap_gemini_processor(monkeypatch):
    """Set up GeminiInstrumentor with a fresh logfire tracer + test exporter."""
    import logfire

    monkeypatch.setenv(
        "GEMINI_API_KEY",
        os.environ.get(
            "GEMINI_API_KEY", "test-dummy-gemini-key-for-vcr-replay"
        ),
    )

    exporter = TestSpanExporter()
    from introspection_sdk import IntrospectionSpanProcessor

    processor = IntrospectionSpanProcessor(
        token="test-token",
        advanced=AdvancedOptions(span_exporter=exporter),
    )
    logfire.configure(
        send_to_logfire=False,
        additional_span_processors=[processor],
        console=False,
    )

    instrumentor = GeminiInstrumentor()
    instrumentor.instrument()

    try:
        yield CaptureSpanProcessor(exporter=exporter, processor=processor)
    finally:
        instrumentor.uninstrument()
        processor.shutdown()


def test_gemini_thinking_basic(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Non-streaming: response part carries a thought_signature."""
    client = genai.Client()
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents="What is 2+2? Think step by step.",
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        ),
    )

    # At least one part should carry a thought_signature
    assert any(
        bool(p.thought_signature) for p in response.candidates[0].content.parts
    )

    cap_gemini_processor.processor.force_flush()
    spans = cap_gemini_processor.exporter.get_finished_spans()

    assert len(spans) >= 1
    span = spans[0]

    assert span == IsPartialDict(
        {
            "name": "chat",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system": "gemini",
                    "gen_ai.provider.name": "gemini",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": GEMINI_MODEL,
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
                                                "signature": IsStr(),
                                                "provider_name": "gemini",
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


def test_gemini_thinking_multi_turn(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Multi-turn: tool call returns 25°C, follow-up asks for Fahrenheit conversion.

    The model must reason over its previous output to convert the temperature.
    Validates that thought_signatures from each turn appear in the next turn's
    input history and that the final answer is approximately correct (~77°F).
    """
    import re

    client = genai.Client()
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_weather",
                description=(
                    "Get weather for a city. Returns conditions and "
                    "temperature in Celsius."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={"city": types.Schema(type=types.Type.STRING)},
                    required=["city"],
                ),
            )
        ]
    )

    config = types.GenerateContentConfig(
        tools=[tool],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    contents: list[Any] = [
        types.Content(
            role="user",
            parts=[types.Part(text="What is the weather in Tokyo?")],
        ),
    ]

    # Turn 1: thinking + function call
    response1 = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    fc_part = next(
        p for p in response1.candidates[0].content.parts if p.function_call
    )
    assert fc_part.function_call.name == "get_weather"

    contents.append(response1.candidates[0].content)
    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name="get_weather",
                    response={"temperature_c": 25, "conditions": "Clear"},
                )
            ],
        )
    )

    # Turn 2: model summarizes tool result
    response2 = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    text_parts = [
        p.text for p in response2.candidates[0].content.parts if p.text
    ]
    assert text_parts

    contents.append(response2.candidates[0].content)
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text="What is that temperature in Fahrenheit?")],
        )
    )

    # Turn 3: model reasons over previous output to convert 25°C → ~77°F
    response3 = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        ),
    )
    answer = "".join(
        p.text or "" for p in response3.candidates[0].content.parts if p.text
    )
    match = re.search(r"(\d+(?:\.\d+)?)\s*°?F", answer)
    assert match, f"Expected Fahrenheit value in response: {answer!r}"
    fahrenheit = float(match.group(1))
    assert abs(fahrenheit - 77.0) <= 2.0, f"Expected ~77°F, got {fahrenheit}°F"

    cap_gemini_processor.processor.force_flush()
    spans = cap_gemini_processor.exporter.get_finished_spans()

    assert len(spans) >= 3

    # Turn 1: output should have thinking (signature) + tool_call
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
                        ),
                        IsPartialDict(
                            {"type": "tool_call", "name": "get_weather"}
                        ),
                    ),
                }
            )
        ]
    )

    # Turn 2: input should contain thinking signature from Turn 1 history
    import json

    turn2_input = json.loads(spans[1]["attributes"]["gen_ai.input.messages"])
    assistant_parts: list[dict[str, Any]] = []
    for msg in turn2_input:
        if msg.get("role") == "assistant":
            assistant_parts.extend(msg.get("parts", []))
    thinking_in_history = [
        p for p in assistant_parts if p.get("type") == "thinking"
    ]
    assert thinking_in_history, (
        "Thinking parts from Turn 1 should appear in Turn 2 input history"
    )
    assert any(p.get("signature") for p in thinking_in_history), (
        "At least one thinking part should carry a thought_signature"
    )

    # Turn 3: output should have a text answer
    turn3_output = spans[2]["attributes"]["gen_ai.output.messages"]
    assert turn3_output == IsJson(
        [
            IsPartialDict(
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": Contains(IsPartialDict({"type": "text"})),
                }
            )
        ]
    )


def test_gemini_thinking_streaming(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Streaming: thought_signature parts accumulated from streamed response."""
    client = genai.Client()
    stream = client.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents="What is 3+3? Think step by step.",
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        ),
    )
    chunks = list(stream)
    assert chunks

    cap_gemini_processor.processor.force_flush()
    spans = cap_gemini_processor.exporter.get_finished_spans()

    assert len(spans) >= 1
    span = spans[0]

    assert span == IsPartialDict(
        {
            "name": "chat",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system": "gemini",
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
                                                "signature": IsStr(),
                                                "provider_name": "gemini",
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


async def test_gemini_thinking_async(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Async path: ``client.aio.models.generate_content`` captures thought signatures.

    Production apps typically use the async client; this asserts the
    ``AsyncModels.generate_content`` patch produces an equivalent span.
    """
    client = genai.Client()
    raw = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents="What is 5+5? Think step by step.",
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        ),
    )
    response = cast(Any, raw)
    assert any(
        bool(p.thought_signature) for p in response.candidates[0].content.parts
    )

    cap_gemini_processor.processor.force_flush()
    spans = cap_gemini_processor.exporter.get_finished_spans()
    assert len(spans) >= 1
    assert spans[0] == IsPartialDict(
        {
            "name": "chat",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system": "gemini",
                    "gen_ai.request.model": GEMINI_MODEL,
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
                                                "signature": IsStr(),
                                                "provider_name": "gemini",
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
