"""OpenAI Agents SDK + Braintrust dual export via introspection.init().

Demonstrates dual export: an OpenAI Agents run (agent + tool spans) is sent to
both Braintrust and Introspection. The Braintrust span processor is placed on
the global TracerProvider; ``introspection.init()`` detects it and wires the
OpenAI Agents SDK into the same pipeline, so the whole run fans out to both.

Run with:
    uv run -m introspection_examples.otel.openai_agents.agents_braintrust_init

Required env vars:
    OPENAI_API_KEY      - OpenAI API key
    BRAINTRUST_API_KEY  - Braintrust API key
    INTROSPECTION_TOKEN - Introspection API token
"""

import asyncio
import os

# Braintrust OTEL compatibility must be enabled before importing braintrust.
os.environ["BRAINTRUST_OTEL_COMPAT"] = "true"

from dotenv import load_dotenv  # noqa: E402

try:
    from agents import Agent, Runner, function_tool  # noqa: E402
    from braintrust.otel import BraintrustSpanProcessor  # noqa: E402
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra openai-agents --extra braintrust"
    ) from e

import introspection_sdk.otel as introspection  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402


def main() -> None:
    load_dotenv()

    # 1. Braintrust span processor on the global provider.
    provider = TracerProvider()
    provider.add_span_processor(
        BraintrustSpanProcessor(parent="project_name:dual-export-init")  # type: ignore[arg-type]
    )
    trace.set_tracer_provider(provider)

    # 2. init() detects the provider + wires the Agents SDK -> dual export.
    introspection.init(service_name="agents-braintrust-init")

    @function_tool
    def get_weather(city: str) -> str:
        """Get weather for a city."""
        return f"It's sunny in {city}."

    agent = Agent(
        name="Weather Agent",
        model="gpt-5-nano",
        instructions="Use the get_weather tool, then answer in one sentence.",
        tools=[get_weather],
    )

    result = asyncio.run(Runner.run(agent, "What's the weather in Tokyo?"))
    print(result.final_output)
    introspection.get_tracer_provider().force_flush()
    print("✓ Exported to Braintrust + Introspection.")


if __name__ == "__main__":
    main()
