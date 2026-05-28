"""
OpenAI Agents SDK Integration Example

Demonstrates using OpenAI Agents SDK's native tracing with Introspection.

Run with:
    uv run -m introspection_examples.otel.openai_agents.example
"""

from dotenv import load_dotenv

load_dotenv()

try:
    from agents import Agent, Runner, function_tool, set_trace_processors
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra openai-agents"
    ) from e

from introspection_sdk import IntrospectionTracingProcessor  # noqa: E402


@function_tool
def get_weather(city: str) -> str:
    """Get the current weather for a given city."""
    weather = {
        "San Francisco": "Foggy, 62°F",
        "Tokyo": "Clear, 68°F",
        "New York": "Sunny, 75°F",
    }
    return weather.get(city, f"Weather data unavailable for {city}")


def main():
    processor = IntrospectionTracingProcessor()
    set_trace_processors([processor])

    agent = Agent(
        name="Weather Assistant",
        instructions="You are a helpful weather assistant. Use the get_weather tool to answer weather questions. Be concise.",
        tools=[get_weather],
    )

    result = Runner.run_sync(
        agent, "What's the weather like in San Francisco and Tokyo?"
    )
    print(f"Agent Response: {result.final_output}")

    processor.shutdown()


if __name__ == "__main__":
    main()
