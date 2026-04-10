"""
OpenAI Agents SDK + Arize Phoenix Integration Example

Demonstrates dual export: OpenAI Agents SDK traces sent to both
Arize Phoenix and Introspection.

Uses OpenInference instrumentation to auto-instrument the OpenAI Agents SDK
and export OTel spans to both Arize (via Phoenix register) and Introspection.

Run with:
    uv run -m introspection_examples.thirdparty.openai_agents_arize

Required env vars:
    OPENAI_API_KEY       - OpenAI API key
    ARIZE_SPACE_KEY      - Arize space key
    ARIZE_API_KEY        - Arize API key
    INTROSPECTION_TOKEN  - Introspection API token
"""

import os

try:
    from agents import Agent, Runner
    from openinference.instrumentation.openai_agents import (
        OpenAIAgentsInstrumentor,
    )
    from phoenix.otel import register
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra openai-agents --extra arize && "
        "uv pip install openinference-instrumentation-openai-agents"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def main():
    tracer_provider = register(
        project_name="dual-export-example",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ["ARIZE_SPACE_KEY"],
            "api_key": os.environ["ARIZE_API_KEY"],
        },
        batch=False,
    )

    introspection_processor = IntrospectionSpanProcessor(
        service_name="openai-agents-arize-example",
    )
    tracer_provider.add_span_processor(
        introspection_processor,
    )

    OpenAIAgentsInstrumentor().instrument(tracer_provider=tracer_provider)

    agent = Agent(
        name="Assistant",
        instructions="You are a helpful assistant. Be concise.",
    )

    result = Runner.run_sync(agent, "Say hello in one word.")
    print(f"Agent Response: {result.final_output}")

    OpenAIAgentsInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
