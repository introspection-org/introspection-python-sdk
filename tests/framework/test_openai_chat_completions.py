"""Tests for LLM provider outputs."""

import logfire
import openai
import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import IsJson, IsPartialDict, IsPositiveInt, IsStr
from inline_snapshot import snapshot
from openai import AsyncOpenAI

pytestmark = pytest.mark.vcr()


async def test_openai_chat_completion(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Test OpenAI chat completions API with async client."""

    with logfire.span("simple chat completion"):
        response = await openai_async_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        output = response.choices[0].message.content
        assert output is not None
        print(f"Async chat completion: {output}")

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "Chat Completion with {request_data[model]!r}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.provider.name": "openai",
                            "gen_ai.operation.name": "chat",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.system": "openai",
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.response.finish_reasons": IsJson(["stop"]),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "simple chat completion",
                }
            ),
        ]
    )


def _openai_chat_span(cap: CaptureSpanProcessor) -> dict:
    cap.processor.force_flush()
    spans = cap.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "openai"
    ]
    assert chat, "expected an openai chat span"
    return chat[0]


async def test_openai_chat_streaming(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Streaming chat completion."""
    chunks: list[str] = []
    stream = await openai_async_client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": "Count to three."}],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            chunks.append(delta)
    assert "".join(chunks)

    span = _openai_chat_span(cap_span_processor)
    assert span["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "openai",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": IsStr(),
        }
    )


async def test_openai_chat_tool_calling(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Tool/function calling."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    response = await openai_async_client.chat.completions.create(
        model=openai_model,
        messages=[
            {"role": "user", "content": "Weather in Tokyo? Use the tool."}
        ],
        tools=tools,  # type: ignore[arg-type]
    )
    assert response.choices[0].message.tool_calls

    span = _openai_chat_span(cap_span_processor)
    assert "tool_call" in str(
        span["attributes"].get("gen_ai.output.messages", "")
    )


async def test_openai_chat_structured_output(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Structured output via response_format json_schema."""
    import json

    response = await openai_async_client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": "What is 2+2?"}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "answer",
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "integer"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    )
    data = json.loads(response.choices[0].message.content or "{}")
    assert "answer" in data

    span = _openai_chat_span(cap_span_processor)
    assert span["attributes"] == IsPartialDict(
        {"gen_ai.provider.name": "openai", "gen_ai.request.model": IsStr()}
    )


# 64x64 solid red PNG.
_RED_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAeUlEQVR4nO3PQQkA"
    "MAzAwCqpf1ETMxF7HINABFzm7H7dcEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQ"
    "gBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSg"
    "BQ1oQQNa0IAWNKAFj13PLIEAOXyUUwAAAABJRU5ErkJggg=="
)


async def test_openai_chat_vision(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Vision / image input."""
    response = await openai_async_client.chat.completions.create(
        model=openai_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What colour? One word."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{_RED_PNG}"
                        },
                    },
                ],
            }
        ],
    )
    assert response.choices[0].message.content is not None

    span = _openai_chat_span(cap_span_processor)
    assert span["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "openai",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": IsStr(),
        }
    )


async def test_openai_chat_error_invalid_model(
    openai_async_client: AsyncOpenAI,
    cap_span_processor: CaptureSpanProcessor,
):
    """Error path: an invalid model raises an OpenAI API error."""
    with pytest.raises(openai.APIStatusError):
        await openai_async_client.chat.completions.create(
            model="gpt-nonexistent-xyz",
            messages=[{"role": "user", "content": "hi"}],
        )
