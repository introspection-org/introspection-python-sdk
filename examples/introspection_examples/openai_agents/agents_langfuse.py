"""
OpenAI Agents SDK + Langfuse Integration Example

Demonstrates dual export: OpenAI Agents SDK traces sent to both
Langfuse and Introspection.

Uses OpenInference instrumentation to auto-instrument the OpenAI Agents SDK
and export OTel spans to both Langfuse (via OTLP) and Introspection.

Run with:
    uv run -m introspection_examples.thirdparty.openai_agents_langfuse

Required env vars:
    OPENAI_API_KEY        - OpenAI API key
    LANGFUSE_PUBLIC_KEY   - Langfuse public key
    LANGFUSE_SECRET_KEY   - Langfuse secret key
    INTROSPECTION_TOKEN   - Introspection API token
"""

import base64
import os

try:
    from agents import Agent, Runner
    from langfuse import get_client
    from openinference.instrumentation.openai_agents import (
        OpenAIAgentsInstrumentor,
    )
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra openai-agents --extra langfuse && "
        "uv pip install openinference-instrumentation-openai-agents"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LANGFUSE_AUTH = base64.b64encode(
    f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
).decode()

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    + "/api/public/otel"
)
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
    f"Authorization=Basic {LANGFUSE_AUTH}"
)


def main():
    provider = TracerProvider()
    get_client()

    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(langfuse_processor)

    introspection_processor = IntrospectionSpanProcessor(
        service_name="openai-agents-langfuse-example",
    )
    provider.add_span_processor(introspection_processor)

    trace.set_tracer_provider(provider)

    OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)

    agent = Agent(
        name="Assistant",
        instructions="You are a helpful assistant. Be concise.",
    )

    result = Runner.run_sync(agent, "Say hello in one word.")
    print(f"Agent Response: {result.final_output}")

    langfuse_processor.force_flush()
    OpenAIAgentsInstrumentor().uninstrument()


if __name__ == "__main__":
    main()
