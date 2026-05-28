"""
Anthropic Native Instrumentation Example

Uses Introspection's AnthropicInstrumentor to capture the full Anthropic response
including thinking blocks (extended thinking) with signatures. Demonstrates
multi-turn conversation where thinking blocks are replayed in the history
and the model reasons over previous outputs.

Run with:
    uv run -m introspection_examples.anthropic_sdk.anthropic_native
"""

try:
    import anthropic
    from anthropic.types import ThinkingConfigEnabledParam, ToolParam
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: pip install anthropic"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.otel.anthropic import AnthropicInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


def get_weather(city: str) -> str:
    data = {
        "Tokyo": "Clear, 25°C",
        "Paris": "Rainy, 12°C",
    }
    return data.get(city, f"No data for {city}")


def main() -> None:
    provider = TracerProvider()
    provider.add_span_processor(
        IntrospectionSpanProcessor(service_name="anthropic-native-example")
    )
    trace.set_tracer_provider(provider)

    instrumentor = AnthropicInstrumentor()
    instrumentor.instrument(tracer_provider=provider)

    client = anthropic.Anthropic()
    tools: list[ToolParam] = [
        {
            "name": "get_weather",
            "description": "Get weather for a city. Returns conditions and temperature in Celsius.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        },
    ]

    model = "claude-sonnet-4-5-20250929"
    system = "You are a helpful weather assistant. Always use the tool to get weather data. Be concise."
    thinking_config: ThinkingConfigEnabledParam = {
        "type": "enabled",
        "budget_tokens": 5000,
    }
    messages: list = [
        {"role": "user", "content": "What's the weather in Tokyo?"},
    ]

    print("=== Turn 1: Thinking + Tool Call ===")
    response1 = client.messages.create(
        model=model,
        max_tokens=8000,
        system=system,
        thinking=thinking_config,
        tools=tools,
        messages=messages,
    )

    for block in response1.content:
        if block.type == "thinking":
            print(f"  [Thinking] {block.thinking[:80]}...")  # ty: ignore[unresolved-attribute]
        elif block.type == "tool_use":
            print(f"  [Tool] {block.name}({block.input})")  # ty: ignore[unresolved-attribute]

    messages.append({"role": "assistant", "content": response1.content})

    tool_use_block = next(b for b in response1.content if b.type == "tool_use")
    tool_result = get_weather(tool_use_block.input.get("city", ""))  # ty: ignore[invalid-argument-type, unresolved-attribute]
    print(f"  [Result] {tool_result}")
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,  # ty: ignore[unresolved-attribute]
                    "content": tool_result,
                }
            ],
        }
    )

    print("\n=== Turn 2: Tool Result → Model Summarizes ===")
    response2 = client.messages.create(
        model=model,
        max_tokens=8000,
        system=system,
        thinking=thinking_config,
        tools=tools,
        messages=messages,
    )

    for block in response2.content:
        if block.type == "thinking":
            print(f"  [Thinking] {block.thinking[:80]}...")  # ty: ignore[unresolved-attribute]
        elif block.type == "text":
            print(f"  [Response] {block.text[:200]}")  # ty: ignore[unresolved-attribute]

    messages.append({"role": "assistant", "content": response2.content})

    print("\n=== Turn 3: Follow-up — model reasons over previous output ===")
    messages.append(
        {
            "role": "user",
            "content": "What is that temperature in Fahrenheit? And should I bring a jacket?",
        }
    )
    response3 = client.messages.create(
        model=model,
        max_tokens=8000,
        system=system,
        thinking=thinking_config,
        messages=messages,
    )

    for block in response3.content:
        if block.type == "thinking":
            print(f"  [Thinking] {block.thinking[:80]}...")  # ty: ignore[unresolved-attribute]
        elif block.type == "text":
            print(f"  [Response] {block.text[:200]}")  # ty: ignore[unresolved-attribute]

    instrumentor.uninstrument()
    print("\n✓ All turns completed. Thinking blocks captured in traces.")


if __name__ == "__main__":
    main()
