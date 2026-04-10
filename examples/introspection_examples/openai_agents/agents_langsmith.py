"""
OpenAI Agents SDK + LangSmith Integration Example

Demonstrates dual export: OpenAI Agents SDK traces sent to both
LangSmith and Introspection.

Both LangSmith and Introspection implement the OpenAI Agents SDK
TracingProcessor interface, so we simply register both processors.

Run with:
    uv run -m introspection_examples.thirdparty.openai_agents_langsmith

Required env vars:
    OPENAI_API_KEY       - OpenAI API key
    LANGSMITH_API_KEY    - LangSmith API key
    INTROSPECTION_TOKEN  - Introspection API token
"""

try:
    from agents import Agent, Runner, set_trace_processors
    from langsmith.integrations.openai_agents_sdk import (
        OpenAIAgentsTracingProcessor,
    )
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra openai-agents"
    ) from e

from introspection_sdk import IntrospectionTracingProcessor


def main():
    # Both processors implement the same TracingProcessor interface.
    # set_trace_processors accepts a list — traces go to both in parallel.
    langsmith_processor = OpenAIAgentsTracingProcessor()
    introspection_processor = IntrospectionTracingProcessor()

    processors = [langsmith_processor, introspection_processor]
    set_trace_processors(processors)

    agent = Agent(
        name="Assistant",
        instructions="You are a helpful assistant. Be concise.",
    )

    result = Runner.run_sync(agent, "Say hello in one word.")
    print(f"Agent Response: {result.final_output}")

    # Cleanup
    langsmith_processor.force_flush()
    for p in processors:
        p.shutdown()


if __name__ == "__main__":
    main()
