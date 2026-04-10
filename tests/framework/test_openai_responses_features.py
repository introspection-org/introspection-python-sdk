"""Tests for OpenAI Responses API features: MCP tools and encrypted reasoning.

Record actual OpenAI API responses via VCR to validate that the tracing
processor correctly handles MCP tool calls (via DeepWiki) and encrypted
reasoning output items in real API responses.
"""

import json

import pytest
from agents import Agent, ModelSettings, Runner, set_default_openai_client
from conftest import CaptureTracingProcessor
from dirty_equals import Contains, IsJson, IsPartialDict, IsPositiveInt, IsStr
from inline_snapshot import snapshot
from openai import AsyncOpenAI
from openai.types.shared.reasoning import Reasoning

pytestmark = pytest.mark.vcr()


async def test_responses_mcp_deepwiki(
    openai_async_client: AsyncOpenAI,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Responses API with MCP tools via DeepWiki produces tool call spans."""
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    agent = Agent(
        name="MCP DeepWiki Agent",
        model="gpt-4o",
        instructions=(
            "Use the DeepWiki MCP tools to answer questions about code "
            "repositories. Be very concise."
        ),
        model_settings=ModelSettings(
            extra_body={
                "tools": [
                    {
                        "type": "mcp",
                        "server_label": "deepwiki",
                        "server_url": "https://mcp.deepwiki.com/mcp",
                        "require_approval": "never",
                    }
                ],
            },
        ),
    )

    result = await Runner.run(
        agent,
        input=(
            "What programming language is the openai/openai-agents-python "
            "repo written in? One word answer."
        ),
    )
    assert result.final_output is not None

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    # Find response span — should have MCP tool calls in output
    response_spans = [s for s in spans if s["name"] == "response"]
    assert len(response_spans) >= 1

    assert response_spans[0] == snapshot(
        IsPartialDict(
            {
                "name": "response",
                "attributes": IsPartialDict(
                    {
                        "gen_ai.operation.name": "chat",
                        "gen_ai.system": "openai",
                        "gen_ai.request.model": IsStr(),
                        "gen_ai.response.id": IsStr(),
                        "gen_ai.usage.input_tokens": IsPositiveInt,
                        "gen_ai.usage.output_tokens": IsPositiveInt,
                        "gen_ai.system_instructions": IsJson(
                            [
                                {
                                    "type": "text",
                                    "content": "Use the DeepWiki MCP tools to answer questions about code repositories. Be very concise.",
                                }
                            ]
                        ),
                        "gen_ai.input.messages": IsJson(
                            [
                                {
                                    "role": "user",
                                    "parts": [
                                        {
                                            "type": "text",
                                            "content": "What programming language is the openai/openai-agents-python repo written in? One word answer.",
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
                                                    "type": "tool_call",
                                                    "name": IsStr(
                                                        regex="deepwiki/.*"
                                                    ),
                                                }
                                            ),
                                            IsPartialDict(
                                                {
                                                    "type": "tool_call_response",
                                                }
                                            ),
                                            IsPartialDict(
                                                {
                                                    "type": "text",
                                                }
                                            ),
                                        ),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            }
        )
    )

    # Agent span — shows MCP server in tool definitions
    agent_spans = [
        s
        for s in spans
        if s["attributes"].get("openinference.span.kind") == "AGENT"
    ]
    assert len(agent_spans) >= 1
    assert agent_spans[0] == snapshot(
        IsPartialDict(
            {
                "attributes": IsPartialDict(
                    {
                        "gen_ai.agent.name": "MCP DeepWiki Agent",
                        "gen_ai.system": "openai",
                        "openinference.span.kind": "AGENT",
                    }
                ),
            }
        )
    )


async def test_responses_encrypted_reasoning(
    openai_async_client: AsyncOpenAI,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Responses API with encrypted reasoning produces thinking parts with signature."""
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    agent = Agent(
        name="Encrypted Reasoning Agent",
        model="gpt-5.4",
        instructions="Think carefully before answering.",
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="high", summary="detailed"),
            response_include=["reasoning.encrypted_content"],
        ),
    )

    result = await Runner.run(
        agent,
        input=(
            "If a train travels at 120 km/h for 2.5 hours, then slows to "
            "80 km/h for 1.75 hours, what is the total distance and average speed?"
        ),
    )
    assert result.final_output is not None

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    # Find response span — should have thinking parts with signature
    response_spans = [s for s in spans if s["name"] == "response"]
    assert len(response_spans) >= 1

    assert response_spans[0] == snapshot(
        IsPartialDict(
            {
                "name": "response",
                "attributes": IsPartialDict(
                    {
                        "gen_ai.operation.name": "chat",
                        "gen_ai.system": "openai",
                        "gen_ai.request.model": IsStr(),
                        "gen_ai.response.id": IsStr(),
                        "gen_ai.usage.input_tokens": IsPositiveInt,
                        "gen_ai.usage.output_tokens": IsPositiveInt,
                        "gen_ai.system_instructions": IsJson(
                            [
                                {
                                    "type": "text",
                                    "content": "Think carefully before answering.",
                                }
                            ]
                        ),
                        "gen_ai.input.messages": IsJson(
                            [
                                {
                                    "role": "user",
                                    "parts": [
                                        {
                                            "type": "text",
                                            "content": "If a train travels at 120 km/h for 2.5 hours, then slows to 80 km/h for 1.75 hours, what is the total distance and average speed?",
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
                                                    "type": "thinking",
                                                    "signature": IsStr(),
                                                }
                                            ),
                                            IsPartialDict(
                                                {
                                                    "type": "text",
                                                }
                                            ),
                                        ),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            }
        )
    )

    # Verify thinking part has actual content (summary) and signature
    output_raw = response_spans[0]["attributes"]["gen_ai.output.messages"]
    output_messages = json.loads(output_raw)
    all_parts = []
    for msg in output_messages:
        all_parts.extend(msg.get("parts", []))

    thinking_parts = [p for p in all_parts if p.get("type") == "thinking"]
    assert len(thinking_parts) >= 1
    # Should have both summary content and encrypted signature
    assert thinking_parts[0].get("signature"), (
        "Expected encrypted content signature"
    )

    # Agent span
    agent_spans = [
        s
        for s in spans
        if s["attributes"].get("openinference.span.kind") == "AGENT"
    ]
    assert len(agent_spans) >= 1
    assert agent_spans[0] == snapshot(
        IsPartialDict(
            {
                "attributes": IsPartialDict(
                    {
                        "gen_ai.agent.name": "Encrypted Reasoning Agent",
                        "gen_ai.system": "openai",
                        "openinference.span.kind": "AGENT",
                    }
                ),
            }
        )
    )
