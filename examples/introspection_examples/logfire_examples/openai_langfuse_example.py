"""
Logfire + Langfuse + Introspection: OpenAI client instrumentation

Run with:
    uv run -m introspection_examples.logfire.openai_langfuse

Required env vars:
    OPENAI_API_KEY      - OpenAI API key
    LANGFUSE_PUBLIC_KEY - Langfuse public key
    LANGFUSE_SECRET_KEY - Langfuse secret key
    INTROSPECTION_TOKEN - Introspection API token
"""

import base64
import os

try:
    import logfire
    import openai
    from langfuse import get_client
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra logfire --extra langfuse"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
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
    get_client()

    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())

    logfire.configure(
        send_to_logfire="if-token-present",
        additional_span_processors=[
            langfuse_processor,
            IntrospectionSpanProcessor(
                service_name="logfire-openai-langfuse-example"
            ),
        ],
    )

    logfire.instrument_openai()

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    print(f"Response: {response.choices[0].message.content}")

    langfuse_processor.force_flush()
    logfire.shutdown()


if __name__ == "__main__":
    main()
