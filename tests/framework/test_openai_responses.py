"""Tests for LLM provider outputs."""

from typing import Any

import logfire
import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import IsInt, IsPartialDict, IsStr
from inline_snapshot import snapshot
from openai import AsyncOpenAI

pytestmark = pytest.mark.vcr()


async def test_openai_responses_simple(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Test OpenAI responses API with async client."""

    with logfire.span("simple responses api"):
        response = await openai_async_client.responses.create(
            model=openai_model,
            input="Say hello in one word.",
            instructions="Reply very concisely.",
        )

        last_output = response.output[-1]
        assert hasattr(last_output, "content")
        last_content = last_output.content[-1]  # type: ignore[union-attr]
        output_text = last_content.text

        assert output_text is not None
        print(f"Async response: {output_text}")

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "Responses API with {gen_ai.request.model!r}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.provider.name": "openai",
                            "gen_ai.operation.name": "chat",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.system": "openai",
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.usage.input_tokens": IsInt(),
                            "gen_ai.usage.output_tokens": IsInt(),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "simple responses api",
                }
            ),
        ]
    )


def _openai_span(cap: CaptureSpanProcessor) -> dict:
    cap.processor.force_flush()
    spans = cap.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "openai"
    ]
    assert chat, "expected an openai span"
    return chat[0]


async def test_openai_responses_function_calling(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Responses API plain function calling."""
    tools: list[Any] = [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        }
    ]
    response = await openai_async_client.responses.create(
        model=openai_model,
        input="Use the get_weather tool for Tokyo.",
        tools=tools,
    )
    assert any(
        getattr(item, "type", None) == "function_call"
        for item in response.output
    )

    span = _openai_span(cap_span_processor)
    assert span["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "openai",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": IsStr(),
        }
    )


async def test_openai_responses_streaming(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Streaming Responses API."""
    deltas: list[str] = []
    stream = await openai_async_client.responses.create(
        model=openai_model,
        input="Count to three.",
        stream=True,
    )
    async for event in stream:
        if getattr(event, "type", "") == "response.output_text.delta":
            deltas.append(getattr(event, "delta", ""))
    assert "".join(deltas)

    span = _openai_span(cap_span_processor)
    assert span["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": IsStr(),
        }
    )
