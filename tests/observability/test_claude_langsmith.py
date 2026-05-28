"""Claude Agent SDK x LangSmith dual-export integration tests.

Now that ``introspection_sdk.testing.claude_vcr`` (Phase 2) gives us a
recording transport, this file replaces the previous setup-only smoke
tests with a real-run test recorded against the live ``claude`` CLI.
Replays deterministically in CI.

The pattern mirrors ``tests/framework/test_claude_logfire.py`` (the
golden combo). Order matters: LangSmith's ``configure_claude_agent_sdk``
patches the original ``ClaudeSDKClient`` in place; ``ClaudeTracingProcessor.configure()``
then subclasses the patched class so introspection sits at the top of
the MRO and observes the full conversation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from introspection_sdk import AdvancedOptions, ClaudeTracingProcessor
from introspection_sdk.testing import TestSpanExporter
from introspection_sdk.testing.claude_vcr import build_claude_transport

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions

HAS_DEPS = True
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )
    from langsmith.integrations.claude_agent_sdk import (
        configure_claude_agent_sdk,
    )
except ImportError:
    HAS_DEPS = False


pytestmark = pytest.mark.skipif(
    not HAS_DEPS,
    reason="claude-agent-sdk or langsmith not installed",
)

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / Path(__file__).stem


@pytest.fixture
def claude_cassette(request: pytest.FixtureRequest) -> Path:
    """Per-test cassette path."""
    return _CASSETTE_DIR / f"{request.node.name}.yaml"


@pytest.fixture
def tolerate_unknown_messages():
    """Skip ``rate_limit_event`` so SDK version skew doesn't break tests."""
    from claude_agent_sdk._internal import message_parser

    original = message_parser.parse_message

    class _Skipped:
        pass

    def _tolerant(data):
        if isinstance(data, dict) and data.get("type") == "rate_limit_event":
            return _Skipped()
        return original(data)

    message_parser.parse_message = _tolerant  # type: ignore[assignment]
    try:
        yield
    finally:
        message_parser.parse_message = original


async def test_claude_langsmith_dual_export(
    claude_cassette: Path,
    tolerate_unknown_messages: None,
):
    """Claude SDK call -> spans captured by Introspection, LangSmith coexists.

    LangSmith's ``configure_claude_agent_sdk`` is called first so it
    instruments the original class; ``ClaudeTracingProcessor.configure()``
    then stacks on top. Asserting that introspection still captures a
    valid ``claude.chat`` span proves the stacking didn't break our
    instrumentation.
    """
    configure_claude_agent_sdk(project_name="introspection-tests")

    exporter = TestSpanExporter()
    processor = ClaudeTracingProcessor(
        advanced=AdvancedOptions(span_exporter=exporter),
    )
    processor.configure()
    try:
        options = ClaudeAgentOptions(
            system_prompt="Reply with exactly one word.",
        )
        transport = build_claude_transport(options, claude_cassette)

        text_output: list[str] = []
        session_id: str | None = None
        async with ClaudeSDKClient(
            options=options, transport=transport
        ) as client:
            await client.query("Pick a fruit.")
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text_output.append(block.text)
                elif isinstance(msg, ResultMessage):
                    session_id = msg.session_id

        assert text_output, "expected at least one TextBlock"
        assert session_id, "expected ResultMessage with session_id"

        processor.force_flush()
        spans = exporter.get_finished_spans()
        chat_spans = [s for s in spans if s["name"] == "claude.chat"]
        assert chat_spans, (
            f"expected claude.chat span; got {[s['name'] for s in spans]}"
        )

        attrs = chat_spans[0]["attributes"]
        assert attrs["gen_ai.system"] == "anthropic"
        assert attrs["gen_ai.operation.name"] == "chat"
        assert "Reply with exactly one word." in attrs.get(
            "gen_ai.system_prompt", ""
        )
    finally:
        processor.shutdown()


def test_claude_agent_options_creation():
    """ClaudeAgentOptions wires through the fields we depend on for tracing."""
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="You are a helpful assistant.",
        include_partial_messages=True,
    )
    assert options.model == "claude-sonnet-4-5-20250929"
    assert options.system_prompt == "You are a helpful assistant."
    assert options.include_partial_messages is True
