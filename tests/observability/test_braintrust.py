"""Braintrust dual export integration tests.

Tests that Braintrust spans are captured and converted by IntrospectionSpanProcessor.
"""

import os
from typing import Any

# Enable Braintrust OTEL compatibility mode (must be set before imports)
os.environ["BRAINTRUST_OTEL_COMPAT"] = "true"

import openai
import pytest
from dirty_equals import IsInt, IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot
from openai import AsyncOpenAI

from .conftest import (
    HAS_BRAINTRUST,
    HAS_OPENINFERENCE,
    CaptureOpenInferenceSpans,
)

try:
    from braintrust import Eval, init_logger, wrap_openai
    from braintrust.otel import BraintrustSpanProcessor
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
except ImportError:
    Eval: Any = None
    init_logger: Any = None
    wrap_openai: Any = None
    BraintrustSpanProcessor: Any = None
    trace: Any = None
    TracerProvider: Any = None

# No VCR recording — Braintrust eval traces embed env vars in payloads
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY", "").startswith("sk-")
    or "dummy" in os.environ.get("OPENAI_API_KEY", ""),
    reason="Braintrust tests require real API keys (no VCR recordings)",
)


def task(input):
    """Task function for Braintrust eval."""
    if TracerProvider is None:
        pytest.skip("Braintrust dependencies not installed")
    assert TracerProvider is not None
    assert BraintrustSpanProcessor is not None
    assert trace is not None
    provider = TracerProvider()
    provider.add_span_processor(
        BraintrustSpanProcessor(parent="project_name:my-project")  # type: ignore[arg-type]
    )
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("otel.task") as span:
        span.set_attribute("input", input)
        result = f"Processed: {input}"
        span.set_attribute("output", result)
        return result


def scores(output, expected):
    """Score function that compares output to expected value."""
    return {"match": output == expected}


@pytest.mark.skipif(
    not HAS_BRAINTRUST,
    reason="Braintrust dependencies not installed. Install with: uv sync --group braintrust",
)
def test_braintrust_eval_otel():
    """Test Braintrust eval with OTel tracing."""
    assert Eval is not None
    Eval(
        "OTEL Integration Example",
        data=[
            {"input": "test1", "expected": "Processed: test1"},
            {"input": "test2", "expected": "Processed: test2"},
        ],
        task=task,
        scores=[scores],
    )


@pytest.mark.skipif(
    not HAS_BRAINTRUST,
    reason="Braintrust dependencies not installed. Install with: uv sync --group braintrust",
)
async def test_braintrust_openai_wrapped(
    openai_async_client: AsyncOpenAI, openai_model: str
):
    """Test Braintrust with wrapped OpenAI client."""
    assert wrap_openai is not None
    assert init_logger is not None

    # Initialize braintrust logger first (registers project via HTTP)
    logger = init_logger(project="My Project")
    logger.log("Hello, world!")

    # Then make the OpenAI call so VCR captures requests in order
    client = wrap_openai(openai_async_client)
    result = await client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": "What is 1+1?"}],
    )
    print(result)


@pytest.mark.skipif(
    not HAS_BRAINTRUST or not HAS_OPENINFERENCE,
    reason="Braintrust/OpenInference dependencies not installed. Install with: uv sync --group braintrust --group arize",
)
def test_braintrust_openai_chat_completion_dual_export(
    braintrust_provider: CaptureOpenInferenceSpans,
):
    """Test that OTel spans are captured, converted to GenAI semconv, and exported to Braintrust."""
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

    braintrust_provider.processor.force_flush()

    spans = braintrust_provider.exporter.get_finished_spans()
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
