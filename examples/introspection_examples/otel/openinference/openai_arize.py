"""
OpenAI + Arize Phoenix Integration Example

Demonstrates dual export of OpenAI traces to both Introspection and Arize Phoenix,
with multi-turn tool calling.

Run with:
    uv run -m introspection_examples.otel.openinference.openai_arize
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
    from phoenix.otel import register
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra arize"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def get_weather(location: str) -> str:
    """Simulated weather lookup."""
    data = {
        "San Francisco": "Foggy, 62°F",
        "Tokyo": "Clear, 68°F",
        "London": "Rainy, 55°F",
    }
    return data.get(location, f"No data for {location}")


def main():
    tracer_provider = register(
        project_name="openai-dual-export",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ["ARIZE_SPACE_KEY"],
            "api_key": os.environ["ARIZE_API_KEY"],
        },
        batch=False,
    )

    introspection_processor = IntrospectionSpanProcessor(
        service_name="openai-arize-example",
    )
    tracer_provider.add_span_processor(introspection_processor)

    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

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

    # Turn 1: Ask about weather (model calls tools)
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

    # Execute tool calls
    assistant_msg = response.choices[0].message
    messages.append(cast(Any, assistant_msg))

    if assistant_msg.tool_calls:
        for tc in assistant_msg.tool_calls:
            fn = getattr(tc, "function", None)
            args = json.loads(fn.arguments) if fn else {}
            result = get_weather(args["location"])
            print(f"Tool call: {fn.name if fn else ''}({args}) -> {result}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

    # Turn 2: Get final response with tool results
    response2 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )
    print(f"Response: {response2.choices[0].message.content}")

    OpenAIInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
