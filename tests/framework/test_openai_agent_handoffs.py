"""OpenAI Agents SDK handoff / multi-agent tracing tests.

Covers the subagent-handoff scenarios called out in
docs/test-quality-audit-plan.md (Phase 3a): triage agent delegating to
specialist agents, nested handoffs, and agents exposed as tools to other
agents. Assertions focus on the span hierarchy and the
``gen_ai.handoff.*`` / ``gen_ai.agent.handoffs`` attributes emitted by
``IntrospectionTracingProcessor``.

Cassettes for these tests still need to be recorded against a real
``OPENAI_API_KEY``; when no cassette exists and only the dummy key is
set, each test skips with an explicit pointer back to the audit plan
rather than failing CI. Once the cassettes land, the skip becomes
inert.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import pytest
from agents import (
    Agent,
    Runner,
    function_tool,
    handoff,
    set_default_openai_client,
)
from conftest import CaptureTracingProcessor
from dirty_equals import IsJson, IsPartialDict, IsStr
from openai import AsyncOpenAI

pytestmark = pytest.mark.vcr()

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / Path(__file__).stem
_DUMMY_KEY_PREFIX = "sk-test-dummy"


@pytest.fixture(autouse=True)
def _skip_if_no_cassette(request: pytest.FixtureRequest) -> None:
    """Skip when no cassette exists and only the dummy OPENAI_API_KEY is set.

    Cassette generation for the Phase 3a handoff tests has to happen in an
    environment with outbound access to api.openai.com and a real key —
    see docs/test-quality-audit-plan.md. Until then, skip rather than
    fail.
    """
    cassette = _CASSETTE_DIR / f"{request.node.name}.yaml"
    if cassette.exists():
        return
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or key.startswith(_DUMMY_KEY_PREFIX):
        pytest.skip(
            f"No cassette at {cassette.relative_to(Path(__file__).parent)} "
            "and OPENAI_API_KEY is missing/dummy; record with "
            "`pytest --record-mode=once` against a real key. "
            "See docs/test-quality-audit-plan.md (Phase 3a)."
        )


def _agent_spans(spans: list[dict]) -> list[dict]:
    # Per-agent spans only: the root workflow span is also kind=AGENT but
    # carries no gen_ai.agent.name, so exclude anything unnamed.
    return [
        s
        for s in spans
        if s.get("attributes", {}).get("openinference.span.kind") == "AGENT"
        and "gen_ai.agent.name" in s.get("attributes", {})
    ]


def _handoff_spans(spans: list[dict]) -> list[dict]:
    return [
        s
        for s in spans
        if "gen_ai.handoff.to_agent" in s.get("attributes", {})
    ]


async def test_agent_handoff_to_specialist(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """A triage agent hands off to a refunds specialist.

    Asserts that:
    - both agents appear as AGENT spans
    - a handoff span is emitted with the correct from/to attribution
    - the triage agent advertises its handoff targets
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    refund_agent = Agent(
        name="Refund Specialist",
        instructions=(
            "You handle refund requests. Always confirm the order id and "
            "respond with a one-sentence confirmation."
        ),
        model=openai_model,
    )

    triage_agent = Agent(
        name="Triage Agent",
        instructions=(
            "You are a triage agent. If the user mentions a refund, hand "
            "off to the Refund Specialist. Otherwise answer directly."
        ),
        handoffs=[handoff(refund_agent)],
        model=openai_model,
    )

    result = await Runner.run(
        triage_agent,
        input="I need a refund for order 4242.",
    )
    assert result.final_output is not None

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    agent_spans = _agent_spans(spans)
    agent_names = {s["attributes"]["gen_ai.agent.name"] for s in agent_spans}
    assert "Triage Agent" in agent_names
    assert "Refund Specialist" in agent_names

    triage_span = next(
        s
        for s in agent_spans
        if s["attributes"]["gen_ai.agent.name"] == "Triage Agent"
    )
    assert triage_span["attributes"] == IsPartialDict(
        {
            "gen_ai.system": "openai",
            "gen_ai.agent.handoffs": IsJson(["Refund Specialist"]),
        }
    )

    handoff_spans = _handoff_spans(spans)
    assert len(handoff_spans) >= 1
    assert handoff_spans[0]["attributes"] == IsPartialDict(
        {
            "gen_ai.handoff.from_agent": "Triage Agent",
            "gen_ai.handoff.to_agent": "Refund Specialist",
        }
    )


async def test_nested_handoffs_three_agents(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Triage → Billing → Refund: nested handoff chain.

    Verifies that each hop emits a handoff span with correct attribution
    and the agent hierarchy is captured in order.
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    refund_agent = Agent(
        name="Refund Specialist",
        instructions="You finalise refunds. Respond in one short sentence.",
        model=openai_model,
    )
    billing_agent = Agent(
        name="Billing Specialist",
        instructions=(
            "You handle billing only. You must NOT process refunds yourself. "
            "Any request that mentions a refund must be handed off to the "
            "Refund Specialist immediately — always use the handoff."
        ),
        handoffs=[handoff(refund_agent)],
        model=openai_model,
    )
    triage_agent = Agent(
        name="Triage Agent",
        instructions=(
            "You are a triage agent and never answer questions yourself. Hand "
            "any billing- or payment-related question off to the Billing "
            "Specialist immediately — always use the handoff."
        ),
        handoffs=[handoff(billing_agent)],
        model=openai_model,
    )

    result = await Runner.run(
        triage_agent,
        input="My card was charged twice and I want a refund.",
    )
    assert result.final_output is not None

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    handoff_pairs = [
        (
            s["attributes"]["gen_ai.handoff.from_agent"],
            s["attributes"]["gen_ai.handoff.to_agent"],
        )
        for s in _handoff_spans(spans)
    ]
    assert ("Triage Agent", "Billing Specialist") in handoff_pairs
    assert ("Billing Specialist", "Refund Specialist") in handoff_pairs

    agent_names = [
        s["attributes"]["gen_ai.agent.name"] for s in _agent_spans(spans)
    ]
    assert agent_names.index("Triage Agent") < agent_names.index(
        "Billing Specialist"
    )
    assert agent_names.index("Billing Specialist") < agent_names.index(
        "Refund Specialist"
    )


async def test_agent_as_tool(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Agent.as_tool composition: a parent agent invokes another agent as a tool.

    Unlike handoffs, ``as_tool`` keeps control on the parent agent and the
    child invocation appears as a function/tool span. This locks in that
    behaviour so we notice if the SDK starts emitting handoff spans for
    ``as_tool`` (or stops emitting tool spans).
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    translator = Agent(
        name="French Translator",
        instructions=(
            "Translate the user input into French. Reply with only the "
            "translation."
        ),
        model=openai_model,
    )

    composer = Agent(
        name="Composer",
        instructions=(
            "You write short bilingual greetings. Use the "
            "translate_to_french tool to get the French version of any "
            "English phrase you produce."
        ),
        tools=[
            translator.as_tool(
                tool_name="translate_to_french",
                tool_description="Translate English text to French.",
            )
        ],
        model=openai_model,
    )

    result = await Runner.run(
        composer, input="Greet the user with 'hello friend'."
    )
    assert result.final_output is not None

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    tool_spans = [
        s
        for s in spans
        if s.get("attributes", {}).get("openinference.span.kind") == "TOOL"
    ]
    tool_names = {s["attributes"]["gen_ai.tool.name"] for s in tool_spans}
    assert "translate_to_french" in tool_names

    # ``as_tool`` should NOT produce a handoff span — invariant guard.
    assert _handoff_spans(spans) == []


async def test_handoff_with_structured_input(
    openai_async_client: AsyncOpenAI,
    openai_model: str,
    cap_tracing_processor: CaptureTracingProcessor,
):
    """Handoff with a typed input + on_handoff callback.

    Exercises the ``input_type`` / ``on_handoff`` parameters of
    ``handoff()`` and asserts the callback was invoked while the span
    still emits the expected from/to attribution.
    """
    set_default_openai_client(openai_async_client, use_for_tracing=False)

    from pydantic import BaseModel, Field

    class EscalationInput(BaseModel):
        order_id: Annotated[str, Field(description="The order id")]
        reason: Annotated[str, Field(description="Why the user is escalating")]

    captured: dict[str, object] = {}

    async def on_escalate(ctx, payload: EscalationInput) -> None:
        captured["order_id"] = payload.order_id
        captured["reason"] = payload.reason

    @function_tool
    def acknowledge(message: str) -> str:
        """Acknowledge an escalation message."""
        return f"acknowledged: {message}"

    escalation_agent = Agent(
        name="Escalation Agent",
        instructions=(
            "You handle escalations. Acknowledge with the acknowledge "
            "tool and respond in one sentence."
        ),
        tools=[acknowledge],
        model=openai_model,
    )

    triage_agent = Agent(
        name="Triage Agent",
        instructions=(
            "You are a triage agent. For order complaints, hand off to "
            "the Escalation Agent and pass along the order id and "
            "reason."
        ),
        handoffs=[
            handoff(
                escalation_agent,
                input_type=EscalationInput,
                on_handoff=on_escalate,
            )
        ],
        model=openai_model,
    )

    result = await Runner.run(
        triage_agent,
        input=(
            "I am escalating order 9001 because the product arrived broken."
        ),
    )
    assert result.final_output is not None
    assert captured.get("order_id") == "9001"
    assert captured.get("reason")

    cap_tracing_processor.processor.force_flush()
    spans = cap_tracing_processor.exporter.get_finished_spans()

    handoff_spans = _handoff_spans(spans)
    assert handoff_spans, "expected at least one handoff span"
    assert handoff_spans[0]["attributes"] == IsPartialDict(
        {
            "gen_ai.handoff.from_agent": "Triage Agent",
            "gen_ai.handoff.to_agent": "Escalation Agent",
        }
    )

    # The escalation agent's tool call should show up downstream.
    tool_spans = [
        s
        for s in spans
        if s.get("attributes", {}).get("openinference.span.kind") == "TOOL"
        and s["attributes"].get("gen_ai.tool.name") == "acknowledge"
    ]
    assert tool_spans, "expected acknowledge tool span"
    assert tool_spans[0]["attributes"] == IsPartialDict(
        {"gen_ai.tool.name": "acknowledge", "gen_ai.tool.input": IsStr()}
    )
