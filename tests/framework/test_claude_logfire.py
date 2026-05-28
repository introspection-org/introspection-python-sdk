"""Golden dual-export test for Claude Agent SDK x Logfire.

Phase 2 of docs/test-quality-audit-plan.md and the first "golden combo"
under the working principle in that doc — every subsequent
framework x observability test follows this shape.

The pattern:

1. A recorded ``RecordingTransport`` captures the CLI conversation on
   first run, persists it as YAML under ``tests/.../cassettes/...``,
   and a ``ReplayTransport`` deterministically replays it on every
   subsequent run. No HTTP, no real subprocess, no mocks.
2. ``ClaudeTracingProcessor`` is configured with a
   ``TestSpanExporter`` so we assert on the spans it captures from the
   real SDK lifecycle.
3. Logfire is configured alongside (``send_to_logfire=False``) to
   prove the two stacks coexist on the same conversation — the
   ``additional_span_processors=[...]`` seam on
   ``ClaudeTracingProcessor`` is the mechanism.

When adding the next combo (Anthropic native x Langfuse, Gemini x
Arize, …), copy this file's structure: build the transport / fixture,
wire the dual processors, assert ``gen_ai.*`` attributes on the
captured spans.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from introspection_sdk import (
    AdvancedOptions,
    ClaudeTracingProcessor,
)
from introspection_sdk.testing import TestSpanExporter
from introspection_sdk.testing.claude_vcr import build_claude_transport

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

HAS_CLAUDE_SDK = True
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )
except ImportError:
    HAS_CLAUDE_SDK = False


pytestmark = pytest.mark.skipif(
    not HAS_CLAUDE_SDK, reason="claude-agent-sdk not installed"
)

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / Path(__file__).stem


@pytest.fixture
def claude_cassette(request: pytest.FixtureRequest) -> Path:
    """Per-test cassette path, mirroring pytest-recording's convention."""
    return _CASSETTE_DIR / f"{request.node.name}.yaml"


@pytest.fixture
def tolerate_unknown_messages():
    """Silence SDK ``MessageParseError`` for forward-compat CLI messages.

    Older ``claude-agent-sdk`` versions don't know newer message types
    (e.g. ``rate_limit_event``) that the CLI started emitting. Skipping
    them keeps the test focused on conversation semantics rather than
    SDK version skew. Remove this fixture once the SDK pins are
    aligned.
    """
    from claude_agent_sdk._internal import message_parser

    original = message_parser.parse_message

    class _Skipped:  # pragma: no cover - sentinel
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


async def test_claude_logfire_dual_export(
    claude_cassette: Path,
    tolerate_unknown_messages: None,
):
    """Claude SDK conversation → spans captured + Logfire coexists.

    Recording: first run against a real ``claude`` CLI writes
    ``cassettes/test_claude_logfire/test_claude_logfire_dual_export.yaml``.
    Subsequent runs replay deterministically.

    To re-record: ``uv run pytest tests/framework/test_claude_logfire.py
    --record-mode=new_episodes``.
    """
    pytest.importorskip("logfire")
    import logfire

    # Logfire configured but exporting nowhere — proves the SDK
    # tolerates an active logfire alongside our processor without
    # double-emitting or fighting for the global tracer provider.
    logfire.configure(send_to_logfire=False, console=False)

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
            await client.query("Pick a color.")
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text_output.append(block.text)
                elif isinstance(msg, ResultMessage):
                    session_id = msg.session_id

        assert text_output, (
            "expected at least one TextBlock from the assistant"
        )
        assert session_id, "expected ResultMessage with a session_id"

        processor.force_flush()
        spans = exporter.get_finished_spans()
        chat_spans = [s for s in spans if s["name"] == "claude.chat"]
        assert chat_spans, (
            f"expected a claude.chat span; got {[s['name'] for s in spans]}"
        )

        attrs = chat_spans[0]["attributes"]
        assert attrs["gen_ai.system"] == "anthropic"
        assert attrs["gen_ai.operation.name"] == "chat"
        assert "Reply with exactly one word." in attrs.get(
            "gen_ai.system_prompt", ""
        )
    finally:
        processor.shutdown()


def test_recording_transport_module_is_importable():
    """Smoke test that the transport module loads without claude-agent-sdk.

    Catches accidental top-level imports of ``claude_agent_sdk`` in
    ``introspection_sdk.testing.claude_vcr`` (it must remain importable
    so non-SDK tests can re-use ``RecordingTransport``'s YAML / scrub
    helpers).
    """
    # If claude_vcr imported claude_agent_sdk at module top level, this
    # test would have failed at module-import time when claude-agent-sdk
    # is absent. Reaching here is the assertion.
    assert "introspection_sdk.testing.claude_vcr" in sys.modules
