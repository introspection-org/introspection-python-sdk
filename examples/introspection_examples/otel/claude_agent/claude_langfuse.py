"""
Claude Agent SDK + Langfuse Integration Example

Demonstrates dual export: Claude Agent SDK traces sent to both
Langfuse and Introspection.

Uses ClaudeTracingProcessor to instrument the Claude Agent SDK and create
OTel Gen AI semantic convention spans. Langfuse receives spans via its
OTLP endpoint as an additional span processor.

Run with:
    uv run -m introspection_examples.otel.claude_agent.claude_langfuse

Required env vars:
    ANTHROPIC_API_KEY     - Claude API key
    LANGFUSE_PUBLIC_KEY   - Langfuse public key
    LANGFUSE_SECRET_KEY   - Langfuse secret key
    INTROSPECTION_TOKEN   - Introspection API token
"""

import asyncio
import base64
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
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra claude-agent-sdk --extra langfuse"
    ) from e

from introspection_sdk import ClaudeTracingProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LANGFUSE_AUTH = base64.b64encode(
    f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
).decode()

LANGFUSE_ENDPOINT = (
    os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    + "/api/public/otel/v1/traces"
)


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
    # Set up Langfuse processor for dual export
    langfuse_exporter = OTLPSpanExporter(
        endpoint=LANGFUSE_ENDPOINT,
        headers={"Authorization": f"Basic {LANGFUSE_AUTH}"},
    )
    langfuse_processor = BatchSpanProcessor(langfuse_exporter)

    # ClaudeTracingProcessor instruments the Claude Agent SDK and sends
    # gen_ai semconv spans to Introspection + Langfuse via additional_span_processors
    processor = ClaudeTracingProcessor(
        additional_span_processors=[langfuse_processor],
    )
    processor.configure()

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
    langfuse_processor.force_flush()
    processor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
