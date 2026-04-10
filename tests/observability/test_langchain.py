"""LangChain dual export integration tests.

Tests that LangChain spans are captured and converted by IntrospectionSpanProcessor.
"""

import os
from typing import Any

import logfire
import pytest
from dirty_equals import IsInt, IsPartialDict, IsStr

from .conftest import HAS_LANGCHAIN, CaptureOpenInferenceSpans

# LangChain imports (may not be installed)
try:
    from langchain.agents import create_agent
except ImportError:
    create_agent: Any = None

pytestmark = pytest.mark.vcr()


@pytest.mark.skipif(
    create_agent is None,
    reason="LangChain dependencies not installed. Install with: uv sync --group langchain",
)
async def test_langchain_agent(openai_model: str):
    """Test LangChain agent with logfire instrumentation."""
    assert create_agent is not None
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_OTEL_ENABLED"] == "true"

    with logfire.span("langchain agent"):

        def get_weather(city: str) -> str:
            """Get weather for a given city."""
            return f"It's always sunny in {city}!"

        agent = create_agent(
            model=f"openai:{openai_model}",
            tools=[get_weather],
            system_prompt="You are a helpful assistant",
        )

        agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "What is the weather in San Francisco?",
                    }
                ]
            }
        )


@pytest.mark.skipif(
    not HAS_LANGCHAIN,
    reason="LangChain dependencies not installed. Install with: uv sync --group langchain",
)
def test_langchain_agent_dual_export(
    langchain_provider: CaptureOpenInferenceSpans,
):
    """Test that LangChain agent spans are captured via LangChainInstrumentor."""
    assert create_agent is not None

    def get_weather(city: str) -> str:
        """Get weather for a given city."""
        return f"It's always sunny in {city}!"

    agent = create_agent(
        model="openai:gpt-5-nano",
        tools=[get_weather],
        system_prompt="You are a helpful assistant",
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "What is the weather in San Francisco?",
                }
            ]
        }
    )
    print(f"\nLangChain Agent Response: {result}")

    langchain_provider.processor.force_flush()

    spans = langchain_provider.exporter.get_finished_spans()
    chat_openai_spans = [
        span for span in spans if span.get("name") == "ChatOpenAI"
    ]
    assert len(chat_openai_spans) >= 1
    for span in chat_openai_spans:
        assert span == IsPartialDict(
            {
                "name": "ChatOpenAI",
                "attributes": IsPartialDict(
                    {
                        "gen_ai.request.model": IsStr(),
                        "gen_ai.system": "openai",
                        "gen_ai.response.id": IsStr(),
                        "gen_ai.usage.input_tokens": IsInt(),
                        "gen_ai.usage.output_tokens": IsInt(),
                    }
                ),
            }
        )
