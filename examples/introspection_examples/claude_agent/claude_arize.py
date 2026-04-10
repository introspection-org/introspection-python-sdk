"""
Claude Agent SDK + Arize Phoenix Integration Example

Demonstrates dual export: Claude Agent SDK traces sent to both
Arize Phoenix and Introspection.

Uses ClaudeTracingProcessor to instrument the Claude Agent SDK and create
OTel Gen AI semantic convention spans. Introspection receives these directly.
Arize receives spans converted to OpenInference format via
OpenInferenceSpanProcessor.

Run with:
    uv run -m introspection_examples.thirdparty.claude_arize

Required env vars:
    ANTHROPIC_API_KEY    - Claude API key
    ARIZE_SPACE_KEY      - Arize space key
    ARIZE_API_KEY        - Arize API key
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
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra claude-agent-sdk --extra arize"
    ) from e

from introspection_sdk import ClaudeTracingProcessor
from introspection_sdk.converters.genai_to_openinference import (
    OpenInferenceSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace.export import BatchSpanProcessor


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
    # Set up Arize exporter wrapped in OpenInference converter.
    # OpenInferenceSpanProcessor converts gen_ai semconv → OpenInference
    # so Arize renders spans properly.
    arize_exporter = OTLPSpanExporter(
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ["ARIZE_SPACE_KEY"],
            "api_key": os.environ["ARIZE_API_KEY"],
        },
    )
    arize_processor = OpenInferenceSpanProcessor(
        BatchSpanProcessor(arize_exporter)
    )

    # ClaudeTracingProcessor instruments the Claude Agent SDK and sends
    # gen_ai semconv spans to Introspection directly, while Arize receives
    # the same spans converted to OpenInference format.
    processor = ClaudeTracingProcessor(
        additional_span_processors=[arize_processor],
        resource_attributes={
            "model_id": "claude-sonnet-4-5-20250929",
            "openinference.project.name": "claude-dual-export-example",
        },
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
                # Streaming delta — print text chunks as they arrive
                delta = message.event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)
            elif isinstance(message, AssistantMessage):
                # Complete assistant message (after streaming finishes)
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print(f"\n[session_id={message.session_id}]")

    # Cleanup
    processor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
