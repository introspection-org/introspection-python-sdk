"""Tests for OpenAI Conversations API.

These tests require a real OpenAI API key and make live API calls
(no VCR cassettes). Set OPENAI_API_KEY to run them.
"""

import os
from typing import Annotated

import logfire
import pytest
from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
)
from openai import AsyncOpenAI

from introspection_sdk.sessions import IntrospectionConversationsSession

_has_real_openai_key = os.environ.get("OPENAI_API_KEY", "").startswith(
    "sk-"
) and "dummy" not in os.environ.get("OPENAI_API_KEY", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _has_real_openai_key,
        reason="OpenAI Conversations tests require a real OPENAI_API_KEY (no VCR cassettes)",
    ),
]


def make_logged_math_tools():
    """Factory that creates math tools with a fresh call log for each test."""
    call_log: list[str] = []

    @function_tool
    def add_logged(
        a: Annotated[float, "First number"],
        b: Annotated[float, "Second number"],
    ) -> float:
        """Add two numbers together."""
        call_log.append(f"add({a}, {b})")
        return a + b

    @function_tool
    def divide_logged(
        a: Annotated[float, "Numerator"], b: Annotated[float, "Denominator"]
    ) -> float:
        """Divide first number by second."""
        call_log.append(f"divide({a}, {b})")
        return a / b

    @function_tool
    def subtract_logged(
        a: Annotated[float, "First number"],
        b: Annotated[float, "Second number"],
    ) -> float:
        """Subtract second number from first."""
        call_log.append(f"subtract({a}, {b})")
        return a - b

    return [add_logged, divide_logged, subtract_logged], call_log


async def test_openai_conversations_session(
    openai_async_client: AsyncOpenAI, openai_model: str
):
    """Test OpenAI Conversations API session for multi-turn conversations.

    Demonstrates:
    - Creating an OpenAIConversationsSession
    - Running multiple turns with context preservation
    - Retrieving the conversation_id for later resumption
    - Getting conversation items/state from the session
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    agent = Agent(
        name="Geography Assistant",
        instructions="Reply very concisely. Keep answers to one sentence.",
        model=openai_model,
    )

    # Create a new OpenAI Conversations session
    session = IntrospectionConversationsSession()

    # Pre-create the conversation_id so we can set it in baggage for all turns
    conversation_id = await session._get_session_id()

    with (
        logfire.span("openai_conversations_session_test"),
        logfire.set_baggage(**{"gen_ai.conversation.id": conversation_id}),
    ):
        # First turn
        result1 = await Runner.run(
            agent,
            "What city is the Golden Gate Bridge in?",
            session=session,
        )
        print(f"Turn 1: {result1.final_output}")
        assert result1.final_output is not None
        assert "san francisco" in result1.final_output.lower()

        # Second turn - agent should remember context
        result2 = await Runner.run(
            agent,
            "What state is it in?",
            session=session,
        )
        print(f"Turn 2: {result2.final_output}")
        assert result2.final_output is not None
        assert "california" in result2.final_output.lower()

        # Third turn - continuing the conversation
        result3 = await Runner.run(
            agent,
            "What country?",
            session=session,
        )
        print(f"Turn 3: {result3.final_output}")
        assert result3.final_output is not None

    # Fetch conversation state outside the agent span
    print(f"\nConversation ID: {conversation_id}")
    items = await session.get_items()
    print(f"Conversation items ({len(items)} total):")
    for i, item in enumerate(items):
        item_type = item.get("type", item.get("role", "unknown"))
        print(f"  [{i}] {item_type}: {str(item)[:100]}...")


async def test_openai_conversations_session_with_tools(
    openai_async_client: AsyncOpenAI, openai_model: str
):
    """Test OpenAI Conversations session with function tools across multiple turns.

    This shows that tool calls are also preserved in the conversation state.
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    tools, call_log = make_logged_math_tools()

    agent = Agent(
        name="Math Assistant",
        instructions=(
            "You are a math assistant. Always use the calculator tools. "
            "Never calculate in your head."
        ),
        tools=tools,
        model=openai_model,
    )

    session = IntrospectionConversationsSession()

    # Pre-create conversation_id for baggage
    conversation_id = await session._get_session_id()

    with (
        logfire.span("conversations_session_with_tools"),
        logfire.set_baggage(**{"gen_ai.conversation.id": conversation_id}),
    ):
        # First calculation
        result1 = await Runner.run(
            agent,
            "What is 10 + 20?",
            session=session,
        )
        print(f"Turn 1: {result1.final_output}")
        assert "30" in str(result1.final_output)

        # Follow-up using previous result
        result2 = await Runner.run(
            agent,
            "Now divide that by 2",
            session=session,
        )
        print(f"Turn 2: {result2.final_output}")
        assert "15" in str(result2.final_output)

        # Another follow-up
        result3 = await Runner.run(
            agent,
            "Subtract 5 from that",
            session=session,
        )
        print(f"Turn 3: {result3.final_output}")
        assert "10" in str(result3.final_output)

    # Fetch conversation state outside the agent span
    items = await session.get_items()
    print(f"\nConversation ID: {conversation_id}")
    print(f"Tool calls made: {call_log}")
    print(f"Total conversation items: {len(items)}")

    # Verify tool calls were recorded
    assert len(call_log) >= 3, f"Expected 3+ tool calls, got: {call_log}"


async def test_resume_openai_conversations_session(
    openai_async_client: AsyncOpenAI, openai_model: str
):
    """Test resuming a conversation from a previous conversation_id.

    Demonstrates creating a new session with an existing conversation_id.
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    agent = Agent(
        name="Assistant",
        instructions="Reply very concisely.",
        model=openai_model,
    )

    # Create initial session and have a conversation
    session1 = IntrospectionConversationsSession()

    # Pre-create conversation_id for baggage
    conversation_id = await session1._get_session_id()

    with (
        logfire.span("resume_conversation_test"),
        logfire.set_baggage(**{"gen_ai.conversation.id": conversation_id}),
    ):
        # First session: establish context
        result1 = await Runner.run(
            agent,
            "My favorite color is blue. Remember this.",
            session=session1,
        )
        print(f"Session 1, Turn 1: {result1.final_output}")
        print(f"Conversation ID: {conversation_id}")

        # Create a NEW session resuming from the same conversation_id
        session2 = IntrospectionConversationsSession(
            conversation_id=conversation_id
        )

        # Continue in the "resumed" session
        result2 = await Runner.run(
            agent,
            "What is my favorite color?",
            session=session2,
        )
        print(f"Session 2 (resumed), Turn 1: {result2.final_output}")

        # The agent should remember from the previous session
        assert "blue" in result2.final_output.lower(), (
            f"Agent should remember 'blue' from previous session: {result2.final_output}"
        )

        logfire.info(
            "Resume conversation test complete",
            conversation_id=conversation_id,
        )
