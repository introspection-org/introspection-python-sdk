"""
Logfire + Introspection: OpenAI client instrumentation

Run with:
    uv run -m introspection_examples.otel.logfire_examples.openai_example

Required env vars:
    OPENAI_API_KEY      - OpenAI API key
    INTROSPECTION_TOKEN - Introspection API token
"""

try:
    import logfire
    import openai
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra logfire"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def main():
    logfire.configure(
        send_to_logfire="if-token-present",
        additional_span_processors=[
            IntrospectionSpanProcessor(service_name="logfire-openai-example")
        ],
    )

    logfire.instrument_openai()

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    print(f"Response: {response.choices[0].message.content}")

    logfire.shutdown()


if __name__ == "__main__":
    main()
