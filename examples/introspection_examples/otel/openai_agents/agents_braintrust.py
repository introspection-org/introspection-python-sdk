"""
OpenAI Agents SDK + Braintrust Integration Example

Demonstrates dual export: OpenAI Agents SDK traces sent to both
Braintrust and Introspection.

Braintrust provides a native BraintrustTracingProcessor that implements the
OpenAI Agents SDK TracingProcessor interface, so we register it alongside
IntrospectionTracingProcessor.

Run with:
    uv run -m introspection_examples.otel.openai_agents.agents_braintrust

Required env vars:
    OPENAI_API_KEY       - OpenAI API key
    BRAINTRUST_API_KEY   - Braintrust API key
    INTROSPECTION_TOKEN  - Introspection API token
"""

try:
    from agents import Agent, Runner, set_trace_processors
    from agents.tracing import TracingProcessor
    from braintrust import init_logger
    from braintrust.wrappers.openai import BraintrustTracingProcessor
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra openai-agents && "
        "uv pip install 'braintrust[openai-agents]'"
    ) from e

from introspection_sdk import IntrospectionTracingProcessor


def main():
    # Both processors implement the TracingProcessor interface.
    # set_trace_processors accepts a list — traces go to both in parallel.
    braintrust_processor = BraintrustTracingProcessor(
        init_logger("dual-export-example")
    )
    introspection_processor = IntrospectionTracingProcessor()

    processors: list[TracingProcessor] = [
        braintrust_processor,
        introspection_processor,
    ]
    set_trace_processors(processors)

    agent = Agent(
        name="Assistant",
        instructions="You are a helpful assistant. Be concise.",
    )

    result = Runner.run_sync(agent, "Say hello in one word.")
    print(f"Agent Response: {result.final_output}")

    # Cleanup
    braintrust_processor.force_flush()
    for p in processors:
        p.shutdown()


if __name__ == "__main__":
    main()
