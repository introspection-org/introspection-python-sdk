"""Tests for Anthropic API."""

import anthropic
import logfire
import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import IsInt, IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot

pytestmark = pytest.mark.vcr()


async def test_anthropic_messages(
    anthropic_async_client: anthropic.AsyncAnthropic,
    anthropic_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Test Anthropic messages API (async)."""

    with logfire.span("anthropic messages"):
        response = await anthropic_async_client.messages.create(
            model=anthropic_model,
            max_tokens=100,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        first_block = response.content[0]
        assert first_block.type == "text"
        output = first_block.text  # type: ignore[union-attr]
        assert output is not None
        print(f"Async messages: {output}")

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "Message with {request_data[model]!r}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.provider.name": "anthropic",
                            "gen_ai.operation.name": "chat",
                            "gen_ai.request.model": "claude-haiku-4-5",
                            "gen_ai.response.model": IsStr(),
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.usage.input_tokens": IsInt(),
                            "gen_ai.usage.output_tokens": IsInt(),
                            "gen_ai.response.finish_reasons": IsJson(
                                ["end_turn"]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "anthropic messages",
                }
            ),
        ]
    )


async def test_anthropic_tool_use(
    anthropic_async_client: anthropic.AsyncAnthropic,
    anthropic_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Standalone tool use (no extended thinking)."""
    tools = [
        {
            "name": "get_weather",
            "description": "Get weather for a city.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    response = await anthropic_async_client.messages.create(
        model=anthropic_model,
        max_tokens=256,
        tools=tools,  # type: ignore[arg-type]
        messages=[
            {"role": "user", "content": "Use the tool: weather in Tokyo?"}
        ],
    )
    assert any(b.type == "tool_use" for b in response.content)

    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "anthropic"
    ]
    assert chat
    attrs = chat[0]["attributes"]
    assert attrs == IsPartialDict(
        {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": IsStr(),
            "gen_ai.usage.input_tokens": IsInt(),
            "gen_ai.usage.output_tokens": IsInt(),
        }
    )
    assert "tool_call" in str(attrs.get("gen_ai.output.messages", ""))


async def test_anthropic_streaming(
    anthropic_async_client: anthropic.AsyncAnthropic,
    anthropic_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """``messages.stream()`` context-manager streaming."""
    chunks: list[str] = []
    async with anthropic_async_client.messages.stream(
        model=anthropic_model,
        max_tokens=100,
        messages=[{"role": "user", "content": "Count to three."}],
    ) as stream:
        async for text in stream.text_stream:
            chunks.append(text)
        final = await stream.get_final_message()

    assert "".join(chunks)
    assert final.content[0].type == "text"

    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "anthropic"
    ]
    assert chat
    assert chat[0]["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.operation.name": "chat",
        }
    )


async def test_anthropic_error_invalid_model(
    anthropic_async_client: anthropic.AsyncAnthropic,
    cap_span_processor: CaptureSpanProcessor,
):
    """Error path: an invalid model raises an Anthropic API error."""
    with pytest.raises(anthropic.APIStatusError):
        await anthropic_async_client.messages.create(
            model="claude-nonexistent-model",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )


# 64x64 solid red PNG (large enough for the vision APIs to accept).
_RED_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAeUlEQVR4nO3PQQkA"
    "MAzAwCqpf1ETMxF7HINABFzm7H7dcEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQ"
    "gBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSg"
    "BQ1oQQNa0IAWNKAFj13PLIEAOXyUUwAAAABJRU5ErkJggg=="
)


async def test_anthropic_image_input(
    anthropic_async_client: anthropic.AsyncAnthropic,
    anthropic_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Multimodal image input."""
    response = await anthropic_async_client.messages.create(
        model=anthropic_model,
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _RED_PNG,
                        },
                    },
                    {"type": "text", "text": "What colour is this? One word."},
                ],
            }
        ],
    )
    assert response.content

    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "anthropic"
    ]
    assert chat
    assert chat[0]["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": IsStr(),
        }
    )
