"""
Anthropic + Arize Phoenix Integration Example

Demonstrates dual export of Anthropic traces to both Introspection and Arize Phoenix,
including extended thinking (reasoning) with tool calling.

Run with:
    uv run -m introspection_examples.openinference.anthropic_arize
"""

import os

try:
    import anthropic
    from anthropic.types import ToolParam
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    from phoenix.otel import register
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra arize"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def get_weather(location: str) -> str:
    """Simulated weather lookup."""
    weather_data = {
        "San Francisco, CA": "Foggy, 62°F",
        "New York, NY": "Sunny, 75°F",
        "London, UK": "Rainy, 55°F",
        "Tokyo, Japan": "Clear, 68°F",
    }
    return weather_data.get(
        location, f"Weather data not available for {location}"
    )


def main():
    tracer_provider = register(
        project_name="anthropic-dual-export",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ["ARIZE_SPACE_KEY"],
            "api_key": os.environ["ARIZE_API_KEY"],
        },
        batch=False,
    )

    introspection_processor = IntrospectionSpanProcessor(
        service_name="anthropic-arize-example",
    )
    tracer_provider.add_span_processor(introspection_processor)

    AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)

    client = anthropic.Anthropic()

    print("=== 1. Chat with Extended Thinking ===")
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        messages=[
            {
                "role": "user",
                "content": "What is 17 * 23? Think step by step.",
            }
        ],
    )

    for block in response.content:
        if block.type == "thinking":
            print(f"  [Thinking] {block.thinking[:100]}...")  # ty: ignore[unresolved-attribute]
            print(f"  [Signature] {block.signature[:40]}...")  # ty: ignore[unresolved-attribute]
        elif block.type == "text":
            print(f"  [Response] {block.text[:200]}")  # ty: ignore[unresolved-attribute]
    print()

    print("=== 2. Tool Calling with Thinking ===")
    tools: list[ToolParam] = [
        {
            "name": "get_weather",
            "description": "Get the current weather in a given location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    },
                },
                "required": ["location"],
            },
        },
    ]

    messages: list = [
        {
            "role": "user",
            "content": "What's the weather in San Francisco and Tokyo?",
        },
    ]
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        thinking={"type": "enabled", "budget_tokens": 5000},
        tools=tools,
        messages=messages,
    )

    messages.append({"role": "assistant", "content": response.content})
    tool_results = []
    for block in response.content:
        if block.type == "thinking":
            print(f"  [Thinking] {block.thinking[:100]}...")  # ty: ignore[unresolved-attribute]
        elif block.type == "tool_use":
            result = get_weather(block.input["location"])  # ty: ignore[invalid-argument-type, unresolved-attribute]
            print(f"  [Tool call] {block.name}({block.input}) -> {result}")  # ty: ignore[unresolved-attribute]
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,  # ty: ignore[unresolved-attribute]
                    "content": result,
                }
            )

    if tool_results:
        messages.append({"role": "user", "content": tool_results})
        response2 = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            thinking={"type": "enabled", "budget_tokens": 5000},
            tools=tools,
            messages=messages,
        )

        for block in response2.content:
            if block.type == "thinking":
                print(f"  [Thinking] {block.thinking[:100]}...")  # ty: ignore[unresolved-attribute]
            elif block.type == "text":
                print(f"  [Response] {block.text[:200]}")  # ty: ignore[unresolved-attribute]

    AnthropicInstrumentor().uninstrument()
    print("\n✓ All examples completed and traces exported.")


if __name__ == "__main__":
    main()
