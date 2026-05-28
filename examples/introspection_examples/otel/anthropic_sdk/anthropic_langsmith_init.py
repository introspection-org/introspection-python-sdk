"""Anthropic SDK + LangSmith dual export via introspection.init().

Demonstrates dual export: Anthropic calls are sent to both LangSmith and
Introspection. The LangSmith OTLP exporter is placed on the global
TracerProvider; ``introspection.init()`` detects it and attaches Introspection's
pipeline, so one set of spans fans out to both backends.

Run with:
    uv run -m introspection_examples.otel.anthropic_sdk.anthropic_langsmith_init

Required env vars:
    ANTHROPIC_API_KEY   - Anthropic API key
    LANGSMITH_API_KEY   - LangSmith API key
    LANGSMITH_PROJECT   - LangSmith project (optional)
    INTROSPECTION_TOKEN - Introspection API token
"""

import os

from dotenv import load_dotenv

try:
    import anthropic
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv pip install anthropic"
    ) from e

import introspection_sdk.otel as introspection
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def main() -> None:
    load_dotenv()

    # 1. LangSmith OTLP exporter on the global provider.
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="https://api.smith.langchain.com/otel/v1/traces",
                headers={
                    "x-api-key": os.environ.get("LANGSMITH_API_KEY", ""),
                    "Langsmith-Project": os.environ.get(
                        "LANGSMITH_PROJECT", "dual-export-init"
                    ),
                },
            )
        )
    )
    trace.set_tracer_provider(provider)

    # 2. init() detects the provider + instruments Anthropic -> dual export.
    introspection.init(service_name="anthropic-langsmith-init")

    client = anthropic.Anthropic()
    with introspection.conversation():
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=128,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )

    for block in response.content:
        if block.type == "text":
            print(block.text)  # ty: ignore[unresolved-attribute]

    introspection.get_tracer_provider().force_flush()
    print("✓ Exported to LangSmith + Introspection.")


if __name__ == "__main__":
    main()
