import os
from typing import Any

import logfire
import pytest

logfire.configure(send_to_logfire=False, console=False)

try:
    from posthog import Posthog
    from posthog.ai.openai import AsyncOpenAI

    HAS_POSTHOG = True
except ImportError:
    HAS_POSTHOG = False
    AsyncOpenAI: Any = None

pytestmark = [
    pytest.mark.vcr(),
    pytest.mark.skipif(
        not HAS_POSTHOG,
        reason="PostHog dependencies not installed. Install with: pip install posthog",
    ),
]


@pytest.fixture(scope="session")
def posthog_api_key() -> str:
    """Posthog API key from POSTHOG_API_KEY environment variable."""
    return os.environ.get("POSTHOG_API_KEY", "phc-test-dummy-key")


@pytest.fixture(scope="session")
def posthog_openai_async_client(
    posthog_api_key: str,
) -> AsyncOpenAI:
    """Create an async OpenAI client with PostHog and logfire instrumentation."""
    assert AsyncOpenAI is not None
    posthog = Posthog(posthog_api_key, host="https://us.i.posthog.com")

    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", "sk-test-dummy-key"),
        posthog_client=posthog,
    )
    logfire.instrument_openai(client)
    return client


async def test_posthog_openai_chat_completion(
    posthog_openai_async_client: AsyncOpenAI, openai_model: str
):
    """Test OpenAI chat completions API with async client."""
    assert posthog_openai_async_client is not None

    with logfire.span("posthog openai chat completion"):
        response = await posthog_openai_async_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        output = response.choices[0].message.content
        assert output is not None
        print(f"Async chat completion: {output}")
