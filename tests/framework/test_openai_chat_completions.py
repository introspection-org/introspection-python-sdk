"""Tests for LLM provider outputs."""

import logfire
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
