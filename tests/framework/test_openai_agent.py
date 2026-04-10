"""Tests for LLM provider outputs."""

from typing import Annotated

import logfire
import pytest
from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
)
from conftest import CaptureTracingProcessor
from dirty_equals import Contains, IsJson, IsPartialDict, IsPositiveInt, IsStr
from inline_snapshot import snapshot
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

pytestmark = pytest.mark.vcr()


async def test_openai_agent_weather(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Test OpenAI Agent SDK with function tools."""
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    class Weather(BaseModel):
        """Weather information for a city."""

        city: str = Field(description="The city name")
        temperature_range: str = Field(
            description="The temperature range in Celsius"
        )
        conditions: str = Field(description="The weather conditions")

    @function_tool
    def get_weather(
        city: Annotated[str, "The city to get the weather for"],
    ) -> Weather:
        """Get the current weather information for a specified city."""
        return Weather(
            city=city,
            temperature_range="14-20C",
            conditions="Sunny with wind.",
        )

    agent = Agent(
        name="Weather Assistant",
        instructions="You are a helpful weather assistant.",
        tools=[get_weather],
        model=openai_model,
    )

    result = await Runner.run(agent, input="What's the weather in Tokyo?")
    assert result.final_output is not None
    print(f"Agent SDK: {result.final_output}")

    # Capture spans for snapshot
    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a helpful weather assistant.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "get_weather",
                                        "description": "Get the current weather information for a specified city.",
                                        "parameters": {
                                            "properties": {
                                                "city": {
                                                    "description": "The city to get the weather for",
                                                    "title": "City",
                                                    "type": "string",
                                                }
                                            },
                                            "required": ["city"],
                                            "title": "get_weather_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    }
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "What's the weather in Tokyo?",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "get_weather",
                                                        "arguments": '{"city":"Tokyo"}',
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "get_weather",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "get_weather",
                            "gen_ai.tool.input": '{"city":"Tokyo"}',
                            "gen_ai.tool.output": "city='Tokyo' temperature_range='14-20C' conditions='Sunny with wind.'",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a helpful weather assistant.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "get_weather",
                                        "description": "Get the current weather information for a specified city.",
                                        "parameters": {
                                            "properties": {
                                                "city": {
                                                    "description": "The city to get the weather for",
                                                    "title": "City",
                                                    "type": "string",
                                                }
                                            },
                                            "required": ["city"],
                                            "title": "get_weather_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    }
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "What's the weather in Tokyo?",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "get_weather",
                                                "arguments": '{"city":"Tokyo"}',
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "city='Tokyo' temperature_range='14-20C' conditions='Sunny with wind.'",
                                            }
                                        ],
                                    },
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "stop",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "text",
                                                        "content": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Weather Assistant",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.agent.name": "Weather Assistant",
                            "gen_ai.tool.definitions": IsJson(
                                [{"name": "get_weather"}]
                            ),
                            "gen_ai.agent.output_type": "str",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Agent workflow",
                }
            ),
        ]
    )


@function_tool
def add(
    a: Annotated[float, "First number"], b: Annotated[float, "Second number"]
) -> float:
    """Add two numbers together."""
    print(f"[debug] add({a}, {b}) = {a + b}")
    return a + b


@function_tool
def multiply(
    a: Annotated[float, "First number"], b: Annotated[float, "Second number"]
) -> float:
    """Multiply two numbers together."""
    print(f"[debug] multiply({a}, {b}) = {a * b}")
    return a * b


@function_tool
def subtract(
    a: Annotated[float, "First number"], b: Annotated[float, "Second number"]
) -> float:
    """Subtract second number from first."""
    print(f"[debug] subtract({a}, {b}) = {a - b}")
    return a - b


@function_tool
def divide(
    a: Annotated[float, "Numerator"], b: Annotated[float, "Denominator"]
) -> float:
    """Divide first number by second."""
    print(f"[debug] divide({a}, {b}) = {a / b}")
    return a / b


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


async def test_agent_with_chained_tool_calls(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Single prompt that triggers multiple sequential tool calls.

    The model should call add, divide, and subtract in sequence within
    one Runner.run() call. Expected: (5 + 3) / 4 - 10 = 8 / 4 - 10 = 2 - 10 = -8
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    # Fresh tools and log for this test
    tools, call_log = make_logged_math_tools()

    agent = Agent(
        name="Math Assistant",
        instructions=(
            "You are a math assistant. Use the calculator tools to perform calculations. "
            "Always use the tools - never calculate in your head. "
            "Perform operations step by step, using the result of each step in the next."
        ),
        tools=tools,
        model=openai_model,
    )

    prompt = "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that."

    with logfire.span("chained math calculation", prompt=prompt):
        result = await Runner.run(agent, input=prompt)

        logfire.info(
            "Final result: {output}, tool_calls: {tool_calls}",
            output=result.final_output,
            tool_calls=call_log,
        )

        # Validate multiple tools were called
        assert len(call_log) >= 3, f"Expected 3+ tool calls, got: {call_log}"
        print(f"\nTool calls: {call_log}")
        print(f"Final output: {result.final_output}")

        # The answer should be -8: (5+3)/4 - 10 = 8/4 - 10 = 2 - 10 = -8
        assert result.final_output is not None
        assert "-8" in str(result.final_output), (
            f"Expected -8 in output: {result.final_output}"
        )

    # Capture spans for snapshot
    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that.",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "add_logged",
                                                        "arguments": '{"a":5,"b":3}',
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "add_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "add_logged",
                            "gen_ai.tool.input": '{"a":5,"b":3}',
                            "gen_ai.tool.output": "8.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that.",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "add_logged",
                                                "arguments": '{"a":5,"b":3}',
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "8.0",
                                            }
                                        ],
                                    },
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "divide_logged",
                                                        "arguments": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "divide_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "divide_logged",
                            "gen_ai.tool.input": IsStr(),
                            "gen_ai.tool.output": "2.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that.",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "add_logged",
                                                "arguments": '{"a":5,"b":3}',
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "8.0",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "divide_logged",
                                                "arguments": IsStr(),
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "2.0",
                                            }
                                        ],
                                    },
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "subtract_logged",
                                                        "arguments": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "subtract_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "subtract_logged",
                            "gen_ai.tool.input": IsStr(),
                            "gen_ai.tool.output": "-8.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that.",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "add_logged",
                                                "arguments": '{"a":5,"b":3}',
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "8.0",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "divide_logged",
                                                "arguments": IsStr(),
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "2.0",
                                            }
                                        ],
                                    },
                                    {
                                        "role": "assistant",
                                        "parts": [
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": "subtract_logged",
                                                "arguments": IsStr(),
                                            }
                                        ],
                                    },
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "-8.0",
                                            }
                                        ],
                                    },
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "stop",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "text",
                                                        "content": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Math Assistant",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.agent.name": "Math Assistant",
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {"name": "add_logged"},
                                    {"name": "divide_logged"},
                                    {"name": "subtract_logged"},
                                ]
                            ),
                            "gen_ai.agent.output_type": "str",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Agent workflow",
                }
            ),
        ]
    )


async def test_agent_with_previous_response_id(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Single prompt that triggers multiple sequential tool calls.

    The model should call add, divide, and subtract in sequence within
    one Runner.run() call. Expected: (5 + 3) / 4 - 10 = 8 / 4 - 10 = 2 - 10 = -8
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    # Fresh tools and log for this test
    tools, call_log = make_logged_math_tools()

    agent = Agent(
        name="Math Assistant",
        instructions=(
            "You are a math assistant. Use the calculator tools to perform calculations. "
            "Always use the tools - never calculate in your head. "
            "Perform operations step by step, using the result of each step in the next."
        ),
        tools=tools,
        model=openai_model,
    )

    prompt = "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that."

    with logfire.span("math calculation with last response id", prompt=prompt):
        # TODO: Create a conversation id and pass it
        result = await Runner.run(
            agent,
            input=prompt,
            auto_previous_response_id=True,
        )

        logfire.info(
            "Final result: {output}, tool_calls: {tool_calls}",
            output=result.final_output,
            tool_calls=call_log,
        )

        # Validate multiple tools were called
        assert len(call_log) >= 3, f"Expected 3+ tool calls, got: {call_log}"
        print(f"\nTool calls: {call_log}")
        print(f"Final output: {result.final_output}")

        # The answer should be -8: (5+3)/4 - 10 = 8/4 - 10 = 2 - 10 = -8
        assert result.final_output is not None
        assert "-8" in str(result.final_output), (
            f"Expected -8 in output: {result.final_output}"
        )

    # Capture spans for snapshot
    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    assert spans == snapshot(
        [
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "user",
                                        "parts": [
                                            {
                                                "type": "text",
                                                "content": "Calculate: add 5 + 3, then divide the result by 4, then subtract 10 from that.",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "add_logged",
                                                        "arguments": '{"a":5,"b":3}',
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "add_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "add_logged",
                            "gen_ai.tool.input": '{"a":5,"b":3}',
                            "gen_ai.tool.output": "8.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "8.0",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "divide_logged",
                                                        "arguments": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "divide_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "divide_logged",
                            "gen_ai.tool.input": IsStr(),
                            "gen_ai.tool.output": "2.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "2.0",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "tool-calls",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "tool_call",
                                                        "id": IsStr(),
                                                        "name": "subtract_logged",
                                                        "arguments": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "subtract_logged",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.tool.name": "subtract_logged",
                            "gen_ai.tool.input": IsStr(),
                            "gen_ai.tool.output": "-8.0",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "response",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.system_instructions": IsJson(
                                [
                                    {
                                        "type": "text",
                                        "content": "You are a math assistant. Use the calculator tools to perform calculations. Always use the tools - never calculate in your head. Perform operations step by step, using the result of each step in the next.",
                                    }
                                ]
                            ),
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {
                                        "name": "add_logged",
                                        "description": "Add two numbers together.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "add_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "divide_logged",
                                        "description": "Divide first number by second.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "Numerator",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Denominator",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "divide_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                    {
                                        "name": "subtract_logged",
                                        "description": "Subtract second number from first.",
                                        "parameters": {
                                            "properties": {
                                                "a": {
                                                    "description": "First number",
                                                    "title": "A",
                                                    "type": "number",
                                                },
                                                "b": {
                                                    "description": "Second number",
                                                    "title": "B",
                                                    "type": "number",
                                                },
                                            },
                                            "required": ["a", "b"],
                                            "title": "subtract_logged_args",
                                            "type": "object",
                                            "additionalProperties": False,
                                        },
                                    },
                                ]
                            ),
                            "gen_ai.usage.input_tokens": IsPositiveInt,
                            "gen_ai.usage.output_tokens": IsPositiveInt,
                            "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                            "gen_ai.response.id": IsStr(),
                            "gen_ai.input.messages": IsJson(
                                [
                                    {
                                        "role": "tool",
                                        "parts": [
                                            {
                                                "type": "tool_call_response",
                                                "id": IsStr(),
                                                "response": "-8.0",
                                            }
                                        ],
                                    }
                                ]
                            ),
                            "gen_ai.output.messages": IsJson(
                                [
                                    IsPartialDict(
                                        {
                                            "role": "assistant",
                                            "finish_reason": "stop",
                                            "parts": Contains(
                                                IsPartialDict(
                                                    {
                                                        "type": "text",
                                                        "content": IsStr(),
                                                    }
                                                )
                                            ),
                                        }
                                    )
                                ]
                            ),
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Math Assistant",
                    "attributes": IsPartialDict(
                        {
                            "gen_ai.agent.name": "Math Assistant",
                            "gen_ai.tool.definitions": IsJson(
                                [
                                    {"name": "add_logged"},
                                    {"name": "divide_logged"},
                                    {"name": "subtract_logged"},
                                ]
                            ),
                            "gen_ai.agent.output_type": "str",
                        }
                    ),
                }
            ),
            IsPartialDict(
                {
                    "name": "Agent workflow",
                }
            ),
        ]
    )


async def test_agent_with_prepopulated_history(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Continue a conversation from prepopulated history with realistic tool calls.

    Shows how to inject prior conversation history including tool calls.
    Simulated: add(10, 20) = 30, divide(30, 2) = 15, then ask to subtract 5.
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    tools, call_log = make_logged_math_tools()

    agent = Agent(
        name="Math Assistant",
        instructions="You are a helpful math assistant. Use the tools to perform calculations.",
        tools=tools,
        model=openai_model,
    )

    # Prepopulated conversation history with tool calls (Responses API format)
    # Uses: type="message" for user messages, type="function_call" for tool calls,
    # type="function_call_output" for tool results
    history = [
        # Turn 1: User asks, model calls add tool, tool returns result
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "What is 10 + 20?"}],
        },
        {
            "type": "function_call",
            "call_id": "call_abc123",
            "name": "add_logged",
            "arguments": '{"a": 10, "b": 20}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_abc123",
            "output": "30.0",
        },
        # Turn 2: User asks, model calls divide tool, tool returns result
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Now divide that by 2"}
            ],
        },
        {
            "type": "function_call",
            "call_id": "call_def456",
            "name": "divide_logged",
            "arguments": '{"a": 30, "b": 2}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_def456",
            "output": "15.0",
        },
        # Turn 3: User asks to continue (model will call subtract)
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Subtract 5 from that"}
            ],
        },
    ]

    with logfire.span(
        "continue from prepopulated history", history_turns=len(history)
    ):
        result = await Runner.run(agent, input=history)  # type: ignore[arg-type]

        logfire.info(
            "Result: {output}, tool_calls: {tool_calls}",
            output=result.final_output,
            tool_calls=call_log,
        )

        # Should call subtract tool(s) and produce a numeric result
        assert len(call_log) >= 1, f"Expected tool calls, got: {call_log}"
        print(f"\nTool calls: {call_log}")
        print(f"Final output: {result.final_output}")

        assert result.final_output is not None

    # Capture spans for snapshot
    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    # Focus on the first response (prepopulated history input) and last response
    # (final text output). Intermediate tool call turns vary on re-recording.
    response_spans = [s for s in spans if s["name"] == "response"]
    assert len(response_spans) >= 2

    # First response: verify prepopulated history was passed correctly
    assert response_spans[0] == IsPartialDict(
        {
            "name": "response",
            "attributes": IsPartialDict(
                {
                    "gen_ai.system_instructions": IsJson(
                        [
                            {
                                "type": "text",
                                "content": "You are a helpful math assistant. Use the tools to perform calculations.",
                            }
                        ]
                    ),
                    "gen_ai.tool.definitions": IsJson(
                        [
                            {
                                "name": "add_logged",
                                "description": "Add two numbers together.",
                                "parameters": IsPartialDict(
                                    {"type": "object"}
                                ),
                            },
                            {
                                "name": "divide_logged",
                                "description": "Divide first number by second.",
                                "parameters": IsPartialDict(
                                    {"type": "object"}
                                ),
                            },
                            {
                                "name": "subtract_logged",
                                "description": "Subtract second number from first.",
                                "parameters": IsPartialDict(
                                    {"type": "object"}
                                ),
                            },
                        ]
                    ),
                    "gen_ai.usage.input_tokens": IsPositiveInt,
                    "gen_ai.usage.output_tokens": IsPositiveInt,
                    "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                    "gen_ai.response.id": IsStr(),
                    "gen_ai.input.messages": IsJson(
                        [
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "type": "text",
                                        "content": "What is 10 + 20?",
                                    }
                                ],
                            },
                            {
                                "role": "assistant",
                                "parts": [
                                    {
                                        "type": "tool_call",
                                        "id": "call_abc123",
                                        "name": "add_logged",
                                        "arguments": '{"a": 10, "b": 20}',
                                    }
                                ],
                            },
                            {
                                "role": "tool",
                                "parts": [
                                    {
                                        "type": "tool_call_response",
                                        "id": "call_abc123",
                                        "response": "30.0",
                                    }
                                ],
                            },
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "type": "text",
                                        "content": "Now divide that by 2",
                                    }
                                ],
                            },
                            {
                                "role": "assistant",
                                "parts": [
                                    {
                                        "type": "tool_call",
                                        "id": "call_def456",
                                        "name": "divide_logged",
                                        "arguments": '{"a": 30, "b": 2}',
                                    }
                                ],
                            },
                            {
                                "role": "tool",
                                "parts": [
                                    {
                                        "type": "tool_call_response",
                                        "id": "call_def456",
                                        "response": "15.0",
                                    }
                                ],
                            },
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "type": "text",
                                        "content": "Subtract 5 from that",
                                    }
                                ],
                            },
                        ]
                    ),
                    "gen_ai.output.messages": IsJson(
                        [
                            IsPartialDict(
                                {
                                    "role": "assistant",
                                    "finish_reason": "tool-calls",
                                    "parts": Contains(
                                        IsPartialDict(
                                            {
                                                "type": "tool_call",
                                                "id": IsStr(),
                                                "name": IsStr(),
                                                "arguments": IsStr(),
                                            }
                                        )
                                    ),
                                }
                            )
                        ]
                    ),
                }
            ),
        }
    )

    # Last response: verify final text answer
    assert response_spans[-1] == IsPartialDict(
        {
            "name": "response",
            "attributes": IsPartialDict(
                {
                    "gen_ai.usage.input_tokens": IsPositiveInt,
                    "gen_ai.usage.output_tokens": IsPositiveInt,
                    "gen_ai.request.model": "gpt-5-nano-2025-08-07",
                    "gen_ai.output.messages": IsJson(
                        [
                            IsPartialDict(
                                {
                                    "role": "assistant",
                                    "finish_reason": "stop",
                                    "parts": Contains(
                                        IsPartialDict(
                                            {
                                                "type": "text",
                                                "content": IsStr(),
                                            }
                                        )
                                    ),
                                }
                            )
                        ]
                    ),
                }
            ),
        }
    )

    # Agent + workflow spans present
    assert [
        s["name"]
        for s in spans
        if s["name"] in ("Math Assistant", "Agent workflow")
    ] == [
        "Math Assistant",
        "Agent workflow",
    ]
