"""OpenAI Agents SDK + LangSmith dual-export integration tests.

Tests that both LangSmith and Introspection receive traces when both
processors are registered via set_trace_processors.
"""

from collections.abc import Iterator

import pytest
from conftest import CaptureTracingProcessor
from dirty_equals import IsJson, IsPartialDict, IsStr
from testing import TestSpanExporter

from introspection_sdk.config import AdvancedOptions

try:
    from agents import (
        Agent,
        Runner,
        function_tool,
        set_trace_processors,
    )
    from langsmith.integrations.openai_agents_sdk import (
        OpenAIAgentsTracingProcessor,
    )

    from introspection_sdk import IntrospectionTracingProcessor

    HAS_DEPS = True
except (ImportError, RuntimeError):
    HAS_DEPS = False

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_DEPS,
        reason="openai-agents or langsmith dependencies not installed",
    ),
]


@pytest.fixture
def dual_processors() -> Iterator[CaptureTracingProcessor]:
    """Set up both LangSmith + Introspection tracing processors.

    Yields CaptureTracingProcessor with the Introspection exporter/processor.
    """
    exporter = TestSpanExporter()
    introspection_processor = IntrospectionTracingProcessor(
        advanced=AdvancedOptions(span_exporter=exporter),
    )
    langsmith_processor = OpenAIAgentsTracingProcessor()

    processors = [langsmith_processor, introspection_processor]
    set_trace_processors(processors)  # type: ignore[arg-type]

    try:
        yield CaptureTracingProcessor(
            exporter=exporter, processor=introspection_processor
        )
    finally:
        for p in processors:
            p.force_flush()  # type: ignore[union-attr]
            p.shutdown()  # type: ignore[union-attr]


async def test_openai_agents_langsmith_dual_export(
    dual_processors: CaptureTracingProcessor,
):
    """Test that an OpenAI agent with tools produces spans captured by
    both LangSmith and Introspection."""

    @function_tool
    def get_weather(city: str) -> str:
        """Get weather for a given city."""
        return f"It's always sunny in {city}!"

    agent = Agent(
        name="Weather Agent",
        model="gpt-5-nano",
        instructions="You are a helpful assistant.",
        tools=[get_weather],
    )

    result = await Runner.run(agent, "What is the weather in San Francisco?")
    assert result.final_output is not None

    dual_processors.processor.force_flush()
    spans = dual_processors.exporter.get_finished_spans()
    assert len(spans) > 0

    # Verify Introspection captured a response span with GenAI semconv attributes
    response_spans = [s for s in spans if s["name"] == "response"]
    assert len(response_spans) >= 1

    assert response_spans[0] == IsPartialDict(
        {
            "name": "response",
            "attributes": IsPartialDict(
                {
                    "gen_ai.request.model": IsStr(),
                    "gen_ai.input.messages": IsJson(),
                    "gen_ai.output.messages": IsJson(),
                }
            ),
        }
    )


async def test_openai_agents_langsmith_simple(
    dual_processors: CaptureTracingProcessor,
):
    """Test a simple agent (no tools) with dual export."""
    agent = Agent(
        name="Greeter",
        model="gpt-5-nano",
        instructions="You are a helpful assistant. Be concise.",
    )

    result = await Runner.run(agent, "Say hello in one word.")
    assert result.final_output is not None

    dual_processors.processor.force_flush()
    spans = dual_processors.exporter.get_finished_spans()
    assert len(spans) > 0

    response_spans = [s for s in spans if s["name"] == "response"]
    assert len(response_spans) >= 1
    assert response_spans[0] == IsPartialDict(
        {
            "name": "response",
            "attributes": IsPartialDict(
                {
                    "gen_ai.request.model": IsStr(),
                    "gen_ai.system_instructions": IsJson(
                        [
                            {
                                "type": "text",
                                "content": "You are a helpful assistant. Be concise.",
                            }
                        ]
                    ),
                }
            ),
        }
    )
