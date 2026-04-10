"""Unit tests for ClaudeTracingProcessor.

Uses mock SDK classes injected into sys.modules so that
``claude_agent_sdk`` is importable without installing the real package.
Each test creates a processor with a TestSpanExporter, calls configure(),
exercises the patched client, and asserts the resulting span attributes.

Note: The Claude Agent SDK uses subprocess IPC (not HTTP), so VCR cassettes
cannot record its interactions.  Mock classes provide deterministic,
reproducible outputs instead.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest
from dirty_equals import IsJson, IsPartialDict, IsStr
from inline_snapshot import snapshot
from test_utils import IncrementalIdGenerator, TimeGenerator
from testing import TestSpanExporter

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.processors import claude_tracing_processor as _proc_mod
from introspection_sdk.processors.claude_tracing_processor import (
    ClaudeTracingProcessor,
    _build_input_messages,
    _content_blocks_to_parts,
)
from introspection_sdk.schemas.genai import (
    InputMessage,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)

# ---------------------------------------------------------------------------
# Mock Claude Agent SDK types
# ---------------------------------------------------------------------------
# Names MUST match what the processor checks via type(msg).__name__:
#   "AssistantMessage", "UserMessage", "ResultMessage", "StreamEvent"


@dataclass
class MockClaudeAgentOptions:
    model: str | None = None
    system_prompt: Any = None
    include_partial_messages: bool = False
    resume: str | None = None
    agents: dict[str, Any] | None = None


@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Any = None


@dataclass
class ToolResultBlock:
    type: str = "tool_result"
    tool_use_id: str = ""
    content: Any = ""


@dataclass
class AssistantMessage:
    content: list[Any] = field(default_factory=list)
    model: str = ""
    parent_tool_use_id: str | None = None


@dataclass
class UserMessage:
    content: Any = ""
    uuid: str | None = None
    parent_tool_use_id: str | None = None


@dataclass
class ResultMessage:
    subtype: str = "result"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 1
    session_id: str = ""
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None


@dataclass
class StreamEvent:
    uuid: str = ""
    session_id: str = ""
    event: dict[str, Any] = field(default_factory=dict)
    parent_tool_use_id: str | None = None


@dataclass
class MockAgentDefinition:
    description: str = ""
    prompt: str = ""
    model: str = ""
    tools: list[str] = field(default_factory=list)


class MockClaudeSDKClient:
    """Minimal mock that stores options + prompt and yields canned messages."""

    _canned_messages: list[Any] = []

    def __init__(self, *, options: Any = None):
        self._options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any):
        pass

    async def query(self, prompt: Any = None, **kwargs: Any) -> Any:
        self._prompt = prompt
        return None

    async def receive_response(self):
        for msg in self._canned_messages:
            yield msg


# ---------------------------------------------------------------------------
# Fixture: install/uninstall fake claude_agent_sdk in sys.modules
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fake_claude_sdk():
    """Temporarily inject a fake claude_agent_sdk into sys.modules."""
    fake_mod = types.ModuleType("claude_agent_sdk")
    fake_mod.ClaudeSDKClient = MockClaudeSDKClient  # type: ignore[unresolved-attribute]
    fake_mod.ClaudeAgentOptions = MockClaudeAgentOptions  # type: ignore[unresolved-attribute]

    fake_types = types.ModuleType("claude_agent_sdk.types")
    fake_types.StreamEvent = StreamEvent  # type: ignore[unresolved-attribute]

    old_mod = sys.modules.get("claude_agent_sdk")
    old_types = sys.modules.get("claude_agent_sdk.types")

    sys.modules["claude_agent_sdk"] = fake_mod
    sys.modules["claude_agent_sdk.types"] = fake_types

    # Patch the module-level variable so the guard in configure() passes
    old_attr = getattr(_proc_mod, "claude_agent_sdk", None)
    _proc_mod.claude_agent_sdk = fake_mod  # type: ignore[assignment]

    yield

    # Restore previous state
    _proc_mod.claude_agent_sdk = old_attr  # type: ignore[assignment]
    if old_mod is not None:
        sys.modules["claude_agent_sdk"] = old_mod
    else:
        sys.modules.pop("claude_agent_sdk", None)
    if old_types is not None:
        sys.modules["claude_agent_sdk.types"] = old_types
    else:
        sys.modules.pop("claude_agent_sdk.types", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_processor() -> tuple[ClaudeTracingProcessor, TestSpanExporter]:
    exporter = TestSpanExporter()
    proc = ClaudeTracingProcessor(
        advanced=AdvancedOptions(
            span_exporter=exporter,
            id_generator=IncrementalIdGenerator(),
            ns_timestamp_generator=TimeGenerator(),
        ),
    )
    proc.configure()
    return proc, exporter


async def _run_client(
    messages: list[Any],
    prompt: Any = "Hello",
    options: MockClaudeAgentOptions | None = None,
) -> list[dict[str, Any]]:
    """Run a full query+receive_response cycle and return exported spans."""
    proc, exporter = _make_processor()

    import claude_agent_sdk

    claude_agent_sdk.ClaudeSDKClient._canned_messages = messages  # type: ignore[attr-defined]

    opts = options or MockClaudeAgentOptions(model="claude-test")
    async with claude_agent_sdk.ClaudeSDKClient(options=opts) as client:  # type: ignore[arg-type]
        await client.query(prompt)
        async for _ in client.receive_response():
            pass

    proc.force_flush()
    spans = exporter.get_finished_spans()
    proc.shutdown()
    return spans


# ===================================================================
# Tests for _content_blocks_to_parts
# ===================================================================
class TestContentBlocksToParts:
    def test_sdk_text_block(self):
        assert _content_blocks_to_parts([TextBlock(text="hello")]) == [
            TextPart(type="text", content="hello")
        ]

    def test_dict_text_block(self):
        assert _content_blocks_to_parts(
            [{"type": "text", "text": "world"}]
        ) == [TextPart(type="text", content="world")]

    def test_dict_text_block_with_content_key(self):
        assert _content_blocks_to_parts(
            [{"type": "text", "content": "fallback"}]
        ) == [TextPart(type="text", content="fallback")]

    def test_sdk_tool_use_block(self):
        block = ToolUseBlock(
            id="tool_1", name="get_weather", input={"city": "SF"}
        )
        assert _content_blocks_to_parts([block]) == [
            ToolCallRequestPart(
                type="tool_call",
                id="tool_1",
                name="get_weather",
                arguments={"city": "SF"},
            )
        ]

    def test_dict_tool_use_block(self):
        block = {
            "type": "tool_use",
            "id": "tool_2",
            "name": "search",
            "input": {"q": "test"},
        }
        assert _content_blocks_to_parts([block]) == [
            ToolCallRequestPart(
                type="tool_call",
                id="tool_2",
                name="search",
                arguments={"q": "test"},
            )
        ]

    def test_sdk_tool_result_block(self):
        block = ToolResultBlock(tool_use_id="tool_1", content="Sunny, 25C")
        assert _content_blocks_to_parts([block]) == [
            ToolCallResponsePart(
                type="tool_call_response",
                id="tool_1",
                response="Sunny, 25C",
            )
        ]

    def test_dict_tool_result_with_list_content(self):
        block = {
            "type": "tool_result",
            "tool_use_id": "tool_3",
            "content": [
                {"type": "text", "text": "Temp: 25C"},
                {"type": "text", "text": "Humidity: 60%"},
            ],
        }
        assert _content_blocks_to_parts([block]) == [
            ToolCallResponsePart(
                type="tool_call_response",
                id="tool_3",
                response="Temp: 25C Humidity: 60%",
            )
        ]

    def test_image_block_dict(self):
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png"},
        }
        assert _content_blocks_to_parts([block]) == [
            TextPart(type="text", content="[image: image/png]")
        ]

    def test_thinking_block_dict(self):
        block = {
            "type": "thinking",
            "thinking": "Let me work through this step by step...",
            "signature": "ErUBCkEYs123",
        }
        assert _content_blocks_to_parts([block]) == [
            ThinkingPart(
                type="thinking",
                content="Let me work through this step by step...",
                signature="ErUBCkEYs123",
                provider_name="anthropic",
            )
        ]

    def test_thinking_block_dict_no_signature(self):
        block = {
            "type": "thinking",
            "thinking": "Reasoning about the problem...",
        }
        assert _content_blocks_to_parts([block]) == [
            ThinkingPart(
                type="thinking",
                content="Reasoning about the problem...",
                signature=None,
                provider_name="anthropic",
            )
        ]

    def test_thinking_block_dict_empty_thinking(self):
        block = {
            "type": "thinking",
            "thinking": "",
            "signature": "sig123",
        }
        assert _content_blocks_to_parts([block]) == [
            ThinkingPart(
                type="thinking",
                content=None,
                signature="sig123",
                provider_name="anthropic",
            )
        ]

    def test_empty_content(self):
        assert _content_blocks_to_parts([]) == []
        assert _content_blocks_to_parts(None) == []


# ===================================================================
# Tests for _build_input_messages
# ===================================================================
class TestBuildInputMessages:
    def test_string_prompt(self):
        msgs: list[InputMessage] = []
        _build_input_messages("Hello world", msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Hello world")],
            )
        ]

    def test_dict_prompt_with_message_wrapper(self):
        prompt = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Analyze this codebase",
            },
        }
        msgs: list[InputMessage] = []
        _build_input_messages(prompt, msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Analyze this codebase")],
            )
        ]

    def test_dict_prompt_direct(self):
        prompt = {"role": "user", "content": "Direct message"}
        msgs: list[InputMessage] = []
        _build_input_messages(prompt, msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Direct message")],
            )
        ]

    def test_list_of_streaming_chunks(self):
        """Captured async generator chunks should combine into one user message."""
        prompt = [
            {"type": "text", "text": "Analyze the following:"},
            {"type": "text", "text": "Temperature: 25C"},
            {"type": "text", "text": "What patterns?"},
        ]
        msgs: list[InputMessage] = []
        _build_input_messages(prompt, msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[
                    TextPart(
                        type="text",
                        content="Analyze the following: Temperature: 25C What patterns?",
                    )
                ],
            )
        ]

    def test_list_of_message_dicts(self):
        prompt = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second"},
        ]
        msgs: list[InputMessage] = []
        _build_input_messages(prompt, msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="First")],
            ),
            InputMessage(
                role="assistant",
                parts=[TextPart(type="text", content="Response")],
            ),
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Second")],
            ),
        ]

    def test_dict_prompt_with_content_blocks(self):
        prompt = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Look at this image"},
                {
                    "type": "image",
                    "source": {"media_type": "image/jpeg"},
                },
            ],
        }
        msgs: list[InputMessage] = []
        _build_input_messages(prompt, msgs)
        assert msgs == [
            InputMessage(
                role="user",
                parts=[
                    TextPart(type="text", content="Look at this image"),
                    TextPart(type="text", content="[image: image/jpeg]"),
                ],
            )
        ]


# ===================================================================
# Tests for ClaudeTracingProcessor span creation
# ===================================================================
class TestClaudeTracingProcessorSpans:
    async def test_string_prompt_basic(self):
        spans = await _run_client(
            messages=[
                AssistantMessage(
                    content=[TextBlock(text="Hi there!")],
                    model="claude-test",
                ),
                ResultMessage(
                    session_id="sess-123",
                    usage={
                        "input_tokens": 10,
                        "output_tokens": 5,
                    },
                ),
            ],
            prompt="Hello",
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.system": "anthropic",
                                "gen_ai.request.model": "claude-test",
                                "gen_ai.usage.input_tokens": 10,
                                "gen_ai.usage.output_tokens": 5,
                                "gen_ai.conversation.id": "sess-123",
                                "gen_ai.response.id": IsStr(),
                                "gen_ai.input.messages": IsJson(
                                    [
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Hello",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Hi there!",
                                                }
                                            ],
                                        },
                                    ]
                                ),
                                "gen_ai.output.messages": IsJson(
                                    [
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Hi there!",
                                                }
                                            ],
                                        }
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_stream_event_captures_uuid_and_session(self):
        """StreamEvent.uuid -> gen_ai.response.id, session_id -> gen_ai.conversation.id."""
        spans = await _run_client(
            messages=[
                StreamEvent(
                    uuid="evt-uuid-001",
                    session_id="stream-sess-456",
                    event={
                        "type": "content_block_delta",
                        "delta": {
                            "type": "text_delta",
                            "text": "Hello ",
                        },
                    },
                ),
                StreamEvent(
                    uuid="evt-uuid-002",
                    session_id="stream-sess-456",
                    event={
                        "type": "content_block_delta",
                        "delta": {
                            "type": "text_delta",
                            "text": "world!",
                        },
                    },
                ),
                ResultMessage(
                    session_id="stream-sess-456",
                    usage={"input_tokens": 8, "output_tokens": 3},
                ),
            ],
            prompt="Hi",
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.response.id": "evt-uuid-002",
                                "gen_ai.conversation.id": "stream-sess-456",
                                "gen_ai.usage.input_tokens": 8,
                                "gen_ai.usage.output_tokens": 3,
                                "gen_ai.output.messages": IsJson(
                                    [
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Hello world!",
                                                }
                                            ],
                                        }
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_stream_event_deltas_merged_only_when_no_assistant_msg(
        self,
    ):
        """When AssistantMessage provides content, streaming deltas are NOT merged."""
        spans = await _run_client(
            messages=[
                StreamEvent(
                    uuid="evt-1",
                    session_id="s1",
                    event={
                        "type": "content_block_delta",
                        "delta": {
                            "type": "text_delta",
                            "text": "streamed",
                        },
                    },
                ),
                AssistantMessage(
                    content=[TextBlock(text="Full response")],
                    model="claude-test",
                ),
                ResultMessage(session_id="s1"),
            ],
            prompt="test",
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.output.messages": IsJson(
                                    [
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Full response",
                                                }
                                            ],
                                        }
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_system_prompt_string(self):
        opts = MockClaudeAgentOptions(
            model="claude-test",
            system_prompt="You are a helpful assistant.",
        )
        spans = await _run_client(
            messages=[ResultMessage(session_id="s1")],
            prompt="Hi",
            options=opts,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.system_prompt": "You are a helpful assistant.",
                                "gen_ai.system_instructions": IsJson(
                                    [
                                        {
                                            "type": "text",
                                            "content": "You are a helpful assistant.",
                                        }
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_system_prompt_preset_dict(self):
        opts = MockClaudeAgentOptions(
            model="claude-test",
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": "You are the orchestrator.",
            },
        )
        spans = await _run_client(
            messages=[ResultMessage(session_id="s1")],
            prompt="Hi",
            options=opts,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.system_prompt": IsJson(
                                    {
                                        "type": "preset",
                                        "preset": "claude_code",
                                        "append": "You are the orchestrator.",
                                    }
                                ),
                                "gen_ai.system_instructions": IsJson(
                                    [
                                        {
                                            "type": "text",
                                            "content": "You are the orchestrator.",
                                        }
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_agent_definitions(self):
        opts = MockClaudeAgentOptions(
            model="claude-test",
            agents={
                "test_writer": MockAgentDefinition(
                    description="Writes tests",
                    prompt="You are a test engineer.",
                    model="sonnet",
                    tools=["Read", "Write"],
                ),
                "reviewer": MockAgentDefinition(
                    description="Reviews code",
                    prompt="You are a reviewer.",
                    model="haiku",
                    tools=["Read", "Grep"],
                ),
            },
        )
        spans = await _run_client(
            messages=[ResultMessage(session_id="s1")],
            prompt="Hi",
            options=opts,
        )
        # Agent definitions order is not guaranteed (dict iteration),
        # so we check individual attributes rather than a full snapshot
        attrs = spans[0]["attributes"]
        assert "gen_ai.agent.definitions" in attrs
        import json

        agent_defs = json.loads(attrs["gen_ai.agent.definitions"])
        assert len(agent_defs) == 2
        names = {d["name"] for d in agent_defs}
        assert names == {"test_writer", "reviewer"}
        tw = next(d for d in agent_defs if d["name"] == "test_writer")
        assert tw == snapshot(
            {
                "name": "test_writer",
                "description": "Writes tests",
                "prompt": "You are a test engineer.",
                "model": "sonnet",
                "tools": ["Read", "Write"],
            }
        )

    async def test_resume_session_sets_conversation_id(self):
        opts = MockClaudeAgentOptions(
            model="claude-test",
            resume="prev-session-abc",
        )
        spans = await _run_client(
            messages=[ResultMessage(session_id="new-sess")],
            prompt="What was the secret?",
            options=opts,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                # ResultMessage session_id overwrites resume value
                                "gen_ai.conversation.id": "new-sess",
                            }
                        ),
                    }
                )
            ]
        )

    async def test_user_message_with_tool_result(self):
        spans = await _run_client(
            messages=[
                AssistantMessage(
                    content=[
                        ToolUseBlock(
                            id="t1",
                            name="get_weather",
                            input={"city": "SF"},
                        )
                    ],
                    model="claude-test",
                ),
                UserMessage(
                    content=[
                        ToolResultBlock(
                            tool_use_id="t1",
                            content="Foggy, 62F",
                        )
                    ]
                ),
                AssistantMessage(
                    content=[TextBlock(text="The weather in SF is foggy.")],
                    model="claude-test",
                ),
                ResultMessage(
                    session_id="s1",
                    usage={"input_tokens": 50, "output_tokens": 20},
                ),
            ],
            prompt="What's the weather in SF?",
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.usage.input_tokens": 50,
                                "gen_ai.usage.output_tokens": 20,
                                "gen_ai.input.messages": IsJson(
                                    [
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "What's the weather in SF?",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "tool_call",
                                                    "id": "t1",
                                                    "name": "get_weather",
                                                    "arguments": {
                                                        "city": "SF"
                                                    },
                                                }
                                            ],
                                        },
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "type": "tool_call_response",
                                                    "id": "t1",
                                                    "response": "Foggy, 62F",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "The weather in SF is foggy.",
                                                }
                                            ],
                                        },
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_dict_prompt_message_format(self):
        prompt = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Analyze this codebase for security issues",
            },
        }
        spans = await _run_client(
            messages=[
                AssistantMessage(
                    content=[TextBlock(text="Analysis complete.")],
                    model="claude-test",
                ),
                ResultMessage(session_id="s1"),
            ],
            prompt=prompt,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.input.messages": IsJson(
                                    [
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Analyze this codebase for security issues",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Analysis complete.",
                                                }
                                            ],
                                        },
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_captured_streaming_chunks_as_prompt(self):
        """Simulate captured async generator chunks (list of text dicts)."""
        prompt = [
            {"type": "text", "text": "Here is code:"},
            {"type": "text", "text": "def add(a, b): return a + b"},
            {"type": "text", "text": "Review it."},
        ]
        spans = await _run_client(
            messages=[
                AssistantMessage(
                    content=[TextBlock(text="Looks good!")],
                    model="claude-test",
                ),
                ResultMessage(session_id="s1"),
            ],
            prompt=prompt,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.input.messages": IsJson(
                                    [
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Here is code: def add(a, b): return a + b Review it.",
                                                }
                                            ],
                                        },
                                        {
                                            "role": "assistant",
                                            "parts": [
                                                {
                                                    "type": "text",
                                                    "content": "Looks good!",
                                                }
                                            ],
                                        },
                                    ]
                                ),
                            }
                        ),
                    }
                )
            ]
        )

    async def test_no_prompt_no_input_messages(self):
        spans = await _run_client(
            messages=[ResultMessage(session_id="s1")],
            prompt=None,
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.system": "anthropic",
                                "gen_ai.conversation.id": "s1",
                                "gen_ai.response.id": IsStr(),
                            }
                        ),
                    }
                )
            ]
        )
        # Verify input messages are absent
        assert "gen_ai.input.messages" not in spans[0]["attributes"]

    async def test_response_id_generated_when_no_stream_events(self):
        """Without StreamEvent, a UUID is generated for gen_ai.response.id."""
        spans = await _run_client(
            messages=[
                AssistantMessage(
                    content=[TextBlock(text="Reply")],
                    model="m",
                ),
                ResultMessage(session_id="s1"),
            ],
            prompt="Hi",
        )
        assert spans == snapshot(
            [
                IsPartialDict(
                    {
                        "name": "claude.chat",
                        "attributes": IsPartialDict(
                            {
                                "gen_ai.response.id": IsStr(),
                            }
                        ),
                    }
                )
            ]
        )
        # Verify the generated UUID has the expected format
        response_id = spans[0]["attributes"]["gen_ai.response.id"]
        assert len(response_id) == 36
        assert response_id.count("-") == 4


# ===================================================================
# Test include_partial_messages in ClaudeAgentOptions
# ===================================================================
class TestIncludePartialMessages:
    def test_options_with_include_partial_messages(self):
        """Verify ClaudeAgentOptions accepts include_partial_messages=True."""
        opts = MockClaudeAgentOptions(
            model="claude-test",
            include_partial_messages=True,
        )
        assert opts.include_partial_messages is True
