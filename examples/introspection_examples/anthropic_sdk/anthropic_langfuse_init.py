"""Anthropic SDK + Langfuse dual export via introspection.init().

Demonstrates dual export: Anthropic calls are sent to both Langfuse and
Introspection. Instead of wiring processors and an instrumentor by hand, this
configures the Langfuse exporter on the global TracerProvider and then calls
``introspection.init()`` — which detects that provider and attaches
Introspection's pipeline to it, so one set of spans fans out to both backends.

Run with:
    uv run -m introspection_examples.anthropic_sdk.anthropic_langfuse_init

Required env vars:
    ANTHROPIC_API_KEY     - Anthropic API key
    LANGFUSE_PUBLIC_KEY   - Langfuse public key
    LANGFUSE_SECRET_KEY   - Langfuse secret key
    INTROSPECTION_TOKEN   - Introspection API token
"""

import base64
import os

from dotenv import load_dotenv

try:
    import anthropic
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra langfuse && uv pip install anthropic"
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
    langfuse_auth = base64.b64encode(
        f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
    ).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
        os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        + "/api/public/otel"
    )
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
        f"Authorization=Basic {langfuse_auth}"
    )

    # 1. Put the Langfuse exporter on the global provider.
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # 2. One line: detects the provider, attaches Introspection + instruments
    #    the installed frameworks. Now Anthropic calls export to both.
    introspection.init(service_name="anthropic-langfuse-init")

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
    print("✓ Exported to Langfuse + Introspection.")


if __name__ == "__main__":
    main()
