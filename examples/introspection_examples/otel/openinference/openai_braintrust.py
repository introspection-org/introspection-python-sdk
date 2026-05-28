"""
OpenAI + Braintrust Integration Example

Demonstrates dual export of OpenAI traces to both Introspection and Braintrust,
with multi-turn tool calling.

Run with:
    uv run -m introspection_examples.otel.openinference.openai_braintrust
"""

import json
import os
from typing import Any, cast

try:
    import openai
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionToolParam,
    )
    from openinference.instrumentation.openai import OpenAIInstrumentor
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra braintrust"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.config import AdvancedOptions
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


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

    braintrust_processor = IntrospectionSpanProcessor(
        token=os.environ["BRAINTRUST_API_KEY"],
        advanced=AdvancedOptions(
            base_url="https://api.braintrust.dev/otel/v1/traces",
            additional_headers={
                "x-bt-parent": "project_name:dual-export-example",
            },
        ),
    )
    provider.add_span_processor(braintrust_processor)

    introspection_processor = IntrospectionSpanProcessor(
        service_name="openai-braintrust-example",
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

    braintrust_processor.force_flush()
    OpenAIInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
