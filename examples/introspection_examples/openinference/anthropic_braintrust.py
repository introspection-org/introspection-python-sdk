"""
Anthropic + Braintrust Integration Example

Demonstrates dual export of Anthropic traces to both Introspection and Braintrust,
with multi-turn tool calling.

Run with:
    uv run -m introspection_examples.openinference.anthropic_braintrust
"""

import os

try:
    import anthropic
    from anthropic.types import ToolParam
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra braintrust && uv pip install openinference-instrumentation-anthropic"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.config import AdvancedOptions
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


def get_weather(location: str) -> str:
    """Simulated weather lookup."""
    data = {
        "San Francisco, CA": "Foggy, 62°F",
        "Tokyo, Japan": "Clear, 68°F",
        "London, UK": "Rainy, 55°F",
    }
    return data.get(location, f"No data for {location}")


def main():
    provider = TracerProvider()

    braintrust_processor = IntrospectionSpanProcessor(
        token=os.environ["BRAINTRUST_API_KEY"],
        advanced=AdvancedOptions(
            base_url="https://api.braintrust.dev/otel/v1/traces",
            additional_headers={
                "x-bt-parent": "project_name:anthropic-dual-export",
            },
        ),
    )
    provider.add_span_processor(braintrust_processor)

    introspection_processor = IntrospectionSpanProcessor(
        service_name="anthropic-braintrust-example",
    )
    provider.add_span_processor(introspection_processor)

    trace.set_tracer_provider(provider)

    AnthropicInstrumentor().instrument(tracer_provider=provider)

    client = anthropic.Anthropic()
    tools: list[ToolParam] = [
        {
            "name": "get_weather",
            "description": "Get the current weather in a location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state/country",
                    },
                },
                "required": ["location"],
            },
        },
    ]

    # Turn 1: Ask about weather (model calls tools)
    messages: list = [
        {
            "role": "user",
            "content": "What's the weather in San Francisco and Tokyo?",
        },
    ]
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system="You are a helpful weather assistant. Be concise.",
        tools=tools,
        messages=messages,
    )

    # Execute tool calls
    messages.append({"role": "assistant", "content": response.content})
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            result = get_weather(block.input["location"])  # ty: ignore[invalid-argument-type, unresolved-attribute]
            print(f"Tool call: {block.name}({block.input}) -> {result}")  # ty: ignore[unresolved-attribute]
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,  # ty: ignore[unresolved-attribute]
                    "content": result,
                }
            )

    # Turn 2: Send tool results back
    if tool_results:
        messages.append({"role": "user", "content": tool_results})
        response2 = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system="You are a helpful weather assistant. Be concise.",
            tools=tools,
            messages=messages,
        )
        for block in response2.content:
            if block.type == "text":
                print(f"Response: {block.text}")  # ty: ignore[unresolved-attribute]

    braintrust_processor.force_flush()
    AnthropicInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
