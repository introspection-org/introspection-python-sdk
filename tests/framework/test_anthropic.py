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
