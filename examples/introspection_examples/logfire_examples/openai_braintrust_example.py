"""
Logfire + Braintrust + Introspection: OpenAI client instrumentation

Run with:
    uv run -m introspection_examples.logfire.openai_braintrust

Required env vars:
    OPENAI_API_KEY      - OpenAI API key
    BRAINTRUST_API_KEY  - Braintrust API key
    INTROSPECTION_TOKEN - Introspection API token
"""

try:
    import braintrust
    import logfire
    import openai
    from braintrust.otel import BraintrustSpanProcessor
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra logfire --extra braintrust"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def main():
    braintrust.init_logger()

    braintrust_processor = BraintrustSpanProcessor()

    introspection_processor = IntrospectionSpanProcessor(
        service_name="logfire-openai-braintrust-example"
    )

    processors: list = [braintrust_processor, introspection_processor]

    logfire.configure(
        send_to_logfire="if-token-present",
        additional_span_processors=processors,
    )

    logfire.instrument_openai()

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    print(f"Response: {response.choices[0].message.content}")

    braintrust_processor.force_flush()
    logfire.shutdown()


if __name__ == "__main__":
    main()
