import logfire
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

try:
    from langsmith import traceable

    HAS_LANGSMITH = True
except ImportError:
    HAS_LANGSMITH = False

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_LANGSMITH,
        reason="LangSmith dependencies not installed",
    ),
]


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
