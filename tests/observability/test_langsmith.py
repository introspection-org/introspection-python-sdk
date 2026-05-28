import logfire
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

try:
    from agents import Agent, Runner, function_tool, set_trace_processors
    from langsmith import traceable
    from langsmith.wrappers import OpenAIAgentsTracingProcessor

    HAS_LANGSMITH = True
except ImportError:
    HAS_LANGSMITH = False

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_LANGSMITH,
        reason="LangSmith/agents dependencies not installed",
    ),
]


async def test_langsmith_openai_agent_sdk(
    openai_model: str,
):
    @function_tool
    def get_weather(city: str) -> str:
        """Get weather for a given city."""
        return f"It's always sunny in {city}!"

    async def main():
        agent = Agent(
            name="Weather Agent",
            model=openai_model,
            instructions="You are a helpful assistant.",
            tools=[get_weather],
        )

        question = "What is the weather in San Francisco?"
        result = await Runner.run(agent, question)
        print(result.final_output)

    # Add instrumentation with LangSmith only
    # NOTE: logfire.instrument_openai_agents() disabled due to LogfireTraceWrapper
    # abstract class issues in the custom logfire branch
    set_trace_processors([OpenAIAgentsTracingProcessor()])  # type: ignore[list-item]

    with logfire.span("langsmith openai agent sdk"):
        await main()


async def test_langsmith_traceable_chat_completion(
    openai_async_client: AsyncOpenAI, openai_model: str
):
    @traceable
    def format_prompt():
        return [{"role": "user", "content": "Say hello in one word."}]

    @traceable(run_type="llm")
    async def invoke_llm(messages):
        return await openai_async_client.chat.completions.create(
            messages=messages,
            model=openai_model,
        )

    @traceable
    def parse_output(response: ChatCompletion):
        return response.choices[0].message.content

    @traceable
    async def run_pipeline():
        messages = format_prompt()
        response = await invoke_llm(messages)
        return parse_output(response)

    with logfire.span("langsmith traceable chat completion"):
        await run_pipeline()
