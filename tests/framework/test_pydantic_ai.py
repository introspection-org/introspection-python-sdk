"""Tests for Pydantic AI agents.

Based on https://ai.pydantic.dev/
"""

import logfire
import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import IsPartialDict, IsPositiveInt, IsStr
from inline_snapshot import snapshot
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import (
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)

# Configure logfire without sending data, then instrument Pydantic AI
logfire.configure(send_to_logfire=False, console=False)
logfire.instrument_pydantic_ai(version=2)

pytestmark = pytest.mark.vcr()


class Weather(BaseModel):
    """Weather information for a city."""

    city: str = Field(description="The city name")
    temperature_range: str = Field(
        description="The temperature range in Celsius"
    )
    conditions: str = Field(description="The weather conditions")


def get_weather(city: str) -> Weather:
    """Get the current weather information for a specified city."""
    print(f"[debug] get_weather called for {city}")
    return Weather(
        city=city, temperature_range="14-20C", conditions="Sunny with wind."
    )


async def test_pydantic_ai_weather(
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Test Pydantic AI agent with function tools."""
    agent = Agent(
        model=OpenAIResponsesModel(openai_model),
        system_prompt="You are a helpful weather assistant.",
        tools=[get_weather],
    )

    with logfire.span("pydantic_ai weather agent"):
        result = await agent.run("What's the weather in Tokyo?")
        assert result.output is not None
        print(f"Pydantic AI: {result.output}")

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert [
        s for s in spans if s["name"] == f"chat {openai_model}"
    ] == snapshot(
        [
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
        ]
    )


# --- Math tools ---


def add(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number
    """
    print(f"[debug] add({a}, {b}) = {a + b}")
    return a + b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers together.

    Args:
        a: First number
        b: Second number
    """
    print(f"[debug] multiply({a}, {b}) = {a * b}")
    return a * b


def subtract(a: float, b: float) -> float:
    """Subtract second number from first.

    Args:
        a: First number
        b: Second number
    """
    print(f"[debug] subtract({a}, {b}) = {a - b}")
    return a - b


def divide(a: float, b: float) -> float:
    """Divide first number by second.

    Args:
        a: Numerator
        b: Denominator
    """
    print(f"[debug] divide({a}, {b}) = {a / b}")
    return a / b


def make_logged_math_tools():
    """Factory that creates math tools with a fresh call log for each test."""
    call_log: list[str] = []

    def add_logged(a: float, b: float) -> float:
        """Add two numbers together.

        Args:
            a: First number
            b: Second number
        """
        call_log.append(f"add({a}, {b})")
        return a + b

    def divide_logged(a: float, b: float) -> float:
        """Divide first number by second.

        Args:
            a: Numerator
            b: Denominator
        """
        call_log.append(f"divide({a}, {b})")
        return a / b

    def subtract_logged(a: float, b: float) -> float:
        """Subtract second number from first.

        Args:
            a: First number
            b: Second number
        """
        call_log.append(f"subtract({a}, {b})")
        return a - b

    return [add_logged, divide_logged, subtract_logged], call_log


async def test_pydantic_ai_chained_tool_calls(
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Single prompt that triggers multiple sequential tool calls.

    The model should call add, divide, and subtract in sequence within
    one agent.run() call. Expected: (5 + 3) / 4 - 10 = 8 / 4 - 10 = 2 - 10 = -8
    """
    tools, call_log = make_logged_math_tools()

    agent = Agent(
        model=OpenAIResponsesModel(openai_model),
        system_prompt=(
            "You are a math assistant. Use the calculator tools to perform calculations. "
            "Always use the tools - never calculate in your head. "
            "Perform operations step by step, using the result of each step in the next."
        ),
        tools=tools,
    )

    prompt = "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that."

    with logfire.span("pydantic_ai chained math", prompt=prompt):
        result = await agent.run(prompt)

        logfire.info(
            "Final result: {output}, tool_calls: {tool_calls}",
            output=result.output,
            tool_calls=call_log,
        )

        # Validate multiple tools were called
        assert len(call_log) >= 3, f"Expected 3+ tool calls, got: {call_log}"
        print(f"\nTool calls: {call_log}")
        print(f"Final output: {result.output}")

        # The answer should be -8: (5+3)/4 - 10 = 8/4 - 10 = 2 - 10 = -8
        assert result.output is not None
        assert "-8" in str(result.output), (
            f"Expected -8 in output: {result.output}"
        )

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert [
        s for s in spans if s["name"] == f"chat {openai_model}"
    ] == snapshot(
        [
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
        ]
    )


async def test_pydantic_ai_simple_previous_response_id(
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    model = OpenAIResponsesModel(openai_model)
    agent = Agent(model=model)

    with logfire.span("pydantic_ai simple previous response id"):
        result = await agent.run("your name is Julian")
        last_msg = result.all_messages()[-1]
        previous_response_id = last_msg.provider_response_id  # type: ignore[union-attr]
        assert previous_response_id is not None
        logfire.info(
            "Previous response id: {previous_response_id}",
            previous_response_id=previous_response_id,
        )

        # Manually add the previous response id in the baggage
        with (
            logfire.set_baggage(
                **{"gen_ai.request.previous_response_id": previous_response_id}
            ),
        ):
            result = await agent.run(
                "What is your name?",
                model_settings=OpenAIResponsesModelSettings(
                    openai_previous_response_id=previous_response_id
                ),
            )
            print(result.output)

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert [
        s for s in spans if s["name"] == f"chat {openai_model}"
    ] == snapshot(
        [
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.request.previous_response_id": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
        ]
    )


async def test_pydantic_ai_multi_turn_previous_response_id(
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Multi-turn conversation using openai_previous_response_id for server-side state.

    Using model_settings={'openai_previous_response_id': 'auto'} enables automatic
    response chaining via OpenAI's Responses API. The server maintains conversation
    state, so we only need to pass new messages.

    See: https://ai.pydantic.dev/models/openai/#openai-responses-api
    """
    tools, call_log = make_logged_math_tools()

    agent = Agent(
        model=OpenAIResponsesModel(openai_model),
        system_prompt="You are a helpful math assistant. Use the tools to perform calculations.",
        tools=tools,
    )

    with logfire.span("pydantic_ai multi-turn with previous_response_id"):
        # Turn 1: Initial calculation
        with logfire.span("turn 1"):
            result1 = await agent.run("What is 10 + 20?")
            print(f"Turn 1: {result1.output}")
            assert result1.output is not None

        # Turn 2: Continue with previous_response_id='auto'
        # This uses server-side state from the previous response
        with logfire.span("turn 2"):
            result2 = await agent.run(
                "Now divide that by 2",
                model_settings=OpenAIResponsesModelSettings(
                    openai_previous_response_id="auto"
                ),
            )
            print(f"Turn 2: {result2.output}")
            assert result2.output is not None

        # Turn 3: Continue the chain
        with logfire.span("turn 3"):
            result3 = await agent.run(
                "Subtract 5 from that",
                model_settings=OpenAIResponsesModelSettings(
                    openai_previous_response_id="auto"
                ),
            )
            print(f"Turn 3: {result3.output}")
            assert result3.output is not None

        # Validate tool calls: (10+20)=30, 30/2=15, 15-5=10
        # Note: Model may answer from context without calling tools for follow-ups
        print(f"\nTool calls: {call_log}")
        print(
            f"Results: Turn1={result1.output}, Turn2={result2.output}, Turn3={result3.output}"
        )
        # At minimum, the first turn should call add
        assert len(call_log) >= 1, (
            f"Expected at least 1 tool call, got: {call_log}"
        )

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    assert [
        s for s in spans if s["name"] == f"chat {openai_model}"
    ] == snapshot(
        [
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": f"chat {openai_model}",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openai",
                            "gen_ai.system": "openai",
                            "gen_ai.request.model": "gpt-5-nano",
                            "gen_ai.tool.definitions": IsStr(),
                            "gen_ai.input.messages": IsStr(),
                            "gen_ai.output.messages": IsStr(),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.usage.details.reasoning_tokens": IsPositiveInt,
                            "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.response.finish_reasons": ("stop",),
                        }
                    ),
                }
            ),
        ]
    )


async def test_pydantic_ai_structured_output(
    openai_model: str,
    cap_span_processor: CaptureSpanProcessor,
):
    """Test Pydantic AI with structured output using output_schema."""

    class MathResult(BaseModel):
        """Result of a math calculation."""

        expression: str = Field(
            description="The math expression that was calculated"
        )
        result: float = Field(description="The numerical result")
        steps: list[str] = Field(
            description="Steps taken to solve the problem"
        )

    agent = Agent(
        model=OpenAIResponsesModel(openai_model),
        system_prompt="You are a math assistant. Show your work step by step.",
        tools=[add, subtract, multiply, divide],
        output_type=MathResult,
    )

    with logfire.span("pydantic_ai structured output"):
        result = await agent.run("What is 10 + 5 * 2?")

        assert isinstance(result.output, MathResult)
        print(f"Expression: {result.output.expression}")
        print(f"Result: {result.output.result}")
        print(f"Steps: {result.output.steps}")

    # Capture spans for snapshot
    cap_span_processor.processor.force_flush()
    spans = cap_span_processor.exporter.get_finished_spans()

    # The model may take a variable number of turns (tool calls) before
    # producing a final_result, so assert every chat span has the right
    # structural attributes rather than pinning exact span count.
    chat_spans = [s for s in spans if s["name"] == f"chat {openai_model}"]
    assert len(chat_spans) >= 1
    expected_chat_span = IsPartialDict(
        {
            "name": f"chat {openai_model}",
            "attributes": IsPartialDict(
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": "openai",
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": "gpt-5-nano",
                    "gen_ai.tool.definitions": IsStr(),
                    "gen_ai.input.messages": IsStr(),
                    "gen_ai.output.messages": IsStr(),
                    "gen_ai.usage.input_tokens": IsPositiveInt,
                    "gen_ai.usage.output_tokens": IsPositiveInt,
                    "gen_ai.response.model": "gpt-5-nano-2025-08-07",
                    "gen_ai.response.id": IsStr(),
                    "gen_ai.response.finish_reasons": ("stop",),
                }
            ),
        }
    )
    for span in chat_spans:
        assert span == expected_chat_span
