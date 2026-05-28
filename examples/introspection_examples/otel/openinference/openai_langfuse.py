"""
OpenAI + Langfuse Integration Example

Demonstrates dual export of OpenAI traces to both Introspection and Langfuse,
with multi-turn tool calling.

Uses explicit OTEL setup pattern per Langfuse cookbook:
https://langfuse.com/guides/cookbook/otel_integration_python_sdk

Run with:
    uv run -m introspection_examples.otel.openinference.openai_langfuse
"""

import base64
import json
import os
from typing import Any, cast

try:
    import openai
    from langfuse import get_client
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionToolParam,
    )
    from openinference.instrumentation.openai import OpenAIInstrumentor
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra langfuse"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LANGFUSE_AUTH = base64.b64encode(
    f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
).decode()

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    + "/api/public/otel"
)
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
    f"Authorization=Basic {LANGFUSE_AUTH}"
)


def get_weather(location: str) -> str:
    """Simulated weather lookup."""
    data = {
        "San Francisco": "Foggy, 62°F",
        "Tokyo": "Clear, 68°F",
        "London": "Rainy, 55°F",
    }
    return data.get(location, f"No data for {location}")


def main():
    provider = TracerProvider()
    get_client()

    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(langfuse_processor)

    introspection_processor = IntrospectionSpanProcessor(
        service_name="openai-langfuse-example",
    )
    provider.add_span_processor(introspection_processor)

    trace.set_tracer_provider(provider)

    OpenAIInstrumentor().instrument(tracer_provider=provider)

    client = openai.OpenAI()
    tools: list[ChatCompletionToolParam] = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather in a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City name",
                        },
                    },
                    "required": ["location"],
                },
            },
        }
    ]

    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "You are a helpful weather assistant. Be concise.",
        },
        {
            "role": "user",
            "content": "What's the weather in San Francisco and Tokyo?",
        },
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools,
    )

    assistant_msg = response.choices[0].message
    messages.append(cast(Any, assistant_msg))

    if assistant_msg.tool_calls:
        for tc in assistant_msg.tool_calls:
            fn = getattr(tc, "function", None)
            args = json.loads(fn.arguments) if fn else {}
            result = get_weather(args["location"])
            print(f"Tool call: {fn.name if fn else ''}({args}) -> {result}")
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    response2 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )
    print(f"Response: {response2.choices[0].message.content}")

    langfuse_processor.force_flush()
    OpenAIInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
