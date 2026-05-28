"""
Claude Agent SDK + LangSmith Integration Example

Demonstrates dual export: Claude Agent SDK traces sent to both
LangSmith and Introspection.

Uses ClaudeTracingProcessor to instrument the Claude Agent SDK and create
OTel Gen AI semantic convention spans for Introspection. LangSmith receives
traces via its own configure_claude_agent_sdk() wrapper which stacks on top.

Run with:
    uv run -m introspection_examples.otel.claude_agent.claude_langsmith

Required env vars:
    ANTHROPIC_API_KEY    - Claude API key
    LANGSMITH_API_KEY    - LangSmith API key
    INTROSPECTION_TOKEN  - Introspection API token
"""

import asyncio
import os
from typing import Any

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        create_sdk_mcp_server,
        tool,
    )
    from claude_agent_sdk.types import StreamEvent
    from langsmith.integrations.claude_agent_sdk import (
        configure_claude_agent_sdk,
    )
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra claude-agent-sdk"
    ) from e

from introspection_sdk import ClaudeTracingProcessor

os.environ.setdefault("LANGSMITH_TRACING", "true")


@tool(
    "get_weather",
    "Gets the current weather for a given city",
    {
        "city": str,
    },
)
async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
    """Simulated weather lookup tool."""
    city = args["city"]
    weather_data = {
        "San Francisco": "Foggy, 62F",
        "New York": "Sunny, 75F",
        "London": "Rainy, 55F",
        "Tokyo": "Clear, 68F",
    }
    weather = weather_data.get(city, "Weather data not available")
    return {
        "content": [{"type": "text", "text": f"Weather in {city}: {weather}"}]
    }


async def main():
    # ClaudeTracingProcessor instruments the Claude Agent SDK and sends
    # gen_ai semconv spans to Introspection
    processor = ClaudeTracingProcessor()
    processor.configure()

    # LangSmith's wrapper stacks on top via subclassing
    configure_claude_agent_sdk()

    # Create MCP server with the weather tool
    weather_server = create_sdk_mcp_server(
        name="weather",
        version="1.0.0",
        tools=[get_weather],
    )

    # include_partial_messages=True enables StreamEvent messages which provide
    # per-response UUIDs and session_ids for better tracing granularity.
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="You are a friendly travel assistant who helps with weather information.",
        mcp_servers={"weather": weather_server},
        allowed_tools=["mcp__weather__get_weather"],
        include_partial_messages=True,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "What's the weather like in San Francisco and Tokyo?"
        )

        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                delta = message.event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print(f"\n[session_id={message.session_id}]")

    # Cleanup
    processor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
