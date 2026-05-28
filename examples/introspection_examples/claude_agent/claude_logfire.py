"""Claude Agent SDK + Logfire dual-export example.

Pairs ``ClaudeTracingProcessor`` with Logfire so the same Claude Agent
SDK conversation lands in both Introspection (via the Gen AI semantic
convention) and Logfire (via Pydantic's hosted OTel backend or any
``logfire``-compatible endpoint).

Run with::

    uv run -m introspection_examples.claude_agent.claude_logfire

Required env vars:
    ANTHROPIC_API_KEY    - Claude API key (consumed by the ``claude`` CLI)
    INTROSPECTION_TOKEN  - Introspection API token
    LOGFIRE_TOKEN        - Optional; without it logfire stays local

The pattern: Logfire is configured first so it owns the global tracer
provider; ``ClaudeTracingProcessor`` then wraps the Claude SDK and is
given Logfire's batch processor as an ``additional_span_processor``
so spans fan out to both backends.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        create_sdk_mcp_server,
        tool,
    )
except ImportError as exc:
    raise ImportError(
        "claude-agent-sdk is required. "
        "Install with: pip install 'introspection-sdk[claude-agent-sdk]'"
    ) from exc

try:
    import logfire
except ImportError as exc:
    raise ImportError(
        "logfire is required. Install with: pip install logfire"
    ) from exc

from introspection_sdk import ClaudeTracingProcessor


@tool(
    "get_weather",
    "Get the current weather for a city",
    {"city": str},
)
async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
    fixtures = {
        "Tokyo": "Clear, 68F",
        "London": "Rainy, 55F",
        "Lagos": "Humid, 86F",
    }
    weather = fixtures.get(args["city"], "Unknown")
    return {"content": [{"type": "text", "text": weather}]}


async def main() -> None:
    # Logfire owns the global tracer provider. Without LOGFIRE_TOKEN
    # it runs locally; with it, spans go to logfire.pydantic.dev.
    logfire.configure(service_name="claude-agent-logfire-example")

    # ClaudeTracingProcessor builds its own provider for Gen AI
    # semconv spans. Pass logfire's batch processor through
    # additional_span_processors so the same spans land in both
    # backends.
    introspection = ClaudeTracingProcessor()
    introspection.configure()

    weather_server = create_sdk_mcp_server(
        name="weather", version="1.0.0", tools=[get_weather]
    )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="You are a concise weather assistant.",
        mcp_servers={"weather": weather_server},
        allowed_tools=["mcp__weather__get_weather"],
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("What's the weather in Tokyo and Lagos?")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                    elif isinstance(block, ToolUseBlock):
                        print(f"[tool] {block.name}({block.input})")
            elif isinstance(message, ResultMessage):
                print(f"[session={message.session_id}]")

    introspection.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
