"""
Logfire + Introspection: Anthropic client instrumentation

Run with:
    uv run -m introspection_examples.logfire.anthropic

Required env vars:
    ANTHROPIC_API_KEY   - Anthropic API key
    INTROSPECTION_TOKEN - Introspection API token
"""

try:
    import anthropic
    import logfire
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra logfire"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor


def main():
    logfire.configure(
        send_to_logfire="if-token-present",
        additional_span_processors=[
            IntrospectionSpanProcessor(
                service_name="logfire-anthropic-example"
            )
        ],
    )

    logfire.instrument_anthropic()

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    block = response.content[0]
    print(f"Response: {block.text if hasattr(block, 'text') else block}")

    logfire.shutdown()


if __name__ == "__main__":
    main()
