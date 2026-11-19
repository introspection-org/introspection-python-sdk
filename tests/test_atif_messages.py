"""An ATIF trajectory → ``ag_ui.core`` messages (:mod:`introspection_sdk.atif_messages`).

Pure-unit tests of a conversion. The main input is Harbor's own ATIF loading
example (``fixtures/harbor-load-trajectory.json``, see its ``.source``); the
others are that file edited one field at a time.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from ag_ui.core import Message, UserMessage

from introspection_sdk.atif import spans_to_atif
from introspection_sdk.atif_messages import (
    AtifConversionError,
    atif_to_messages,
)

from .test_atif import ATIF_SCHEMA, whole_prompt_spans

HARBOR = json.loads(
    (
        Path(__file__).parent / "fixtures/harbor-load-trajectory.json"
    ).read_text()
)
INSTRUCTION = "Write the filename and the content to /app/recall.txt."
CALL_ID = "toolu_01Rmm2GPxpGq9Er31axjfYRv"


def to_wire(messages: list[Message]) -> list[dict[str, Any]]:
    return [
        m.model_dump(mode="json", by_alias=True, exclude_none=True)
        for m in messages
    ]


def harbor() -> dict[str, Any]:
    return copy.deepcopy(HARBOR)


def test_harbors_example_loads_as_messages_then_the_instruction() -> None:
    messages = atif_to_messages(harbor(), prompt=INSTRUCTION)
    wire = to_wire(messages)
    content = HARBOR["steps"][1]["observation"]["results"][0]["content"]
    assert wire == [
        {
            "id": "atif-step-1",
            "role": "user",
            "content": 'Create a file called hello.txt with "Hello, world!" '
            "as the content.\n",
        },
        {
            "id": "atif-step-2",
            "role": "assistant",
            "toolCalls": [
                {
                    "id": CALL_ID,
                    "type": "function",
                    "function": {
                        "name": "Write",
                        "arguments": json.dumps(
                            {
                                "file_path": "/app/hello.txt",
                                "content": "Hello, world!\n",
                            }
                        ),
                    },
                }
            ],
        },
        {
            "id": f"atif-step-2-result-{CALL_ID}",
            "role": "tool",
            "content": content,
            "toolCallId": CALL_ID,
        },
        {
            "id": "atif-step-3",
            "role": "assistant",
            "content": "Created `/app/hello.txt` containing `Hello, world!`.",
        },
        {"id": "prompt", "role": "user", "content": INSTRUCTION},
    ]


def test_a_model_converts_the_same_as_its_json() -> None:
    trajectory = spans_to_atif(whole_prompt_spans())
    assert atif_to_messages(
        trajectory, prompt=INSTRUCTION
    ) == atif_to_messages(
        trajectory.model_dump(mode="json"), prompt=INSTRUCTION
    )


def test_a_projected_conversation_round_trips_without_its_system_step() -> (
    None
):
    trajectory = spans_to_atif(whole_prompt_spans())
    assert trajectory.steps[0].source == "system"
    wire = to_wire(atif_to_messages(trajectory, prompt="Thanks"))
    assert [(m["role"], m.get("content")) for m in wire] == [
        ("user", "Read the file"),
        ("assistant", "Reading."),
        ("tool", "hello"),
        ("assistant", "It says hello."),
        ("user", "Thanks"),
    ]
    assert wire[2]["toolCallId"] == wire[1]["toolCalls"][0]["id"]


def test_a_last_user_step_is_the_prompt() -> None:
    trajectory = harbor()
    trajectory["steps"].append(
        {"step_id": 4, "source": "user", "message": INSTRUCTION}
    )
    messages = atif_to_messages(trajectory)
    assert messages[-1] == UserMessage(id="atif-step-4", content=INSTRUCTION)


def test_a_failed_result_carries_its_error() -> None:
    trajectory = harbor()
    trajectory["steps"][1]["observation"]["results"][0]["extra"] = {
        "is_error": True
    }
    tool = to_wire(atif_to_messages(trajectory, prompt=INSTRUCTION))[2]
    assert tool["error"] == tool["content"]


def test_a_failed_result_without_content_still_names_a_failure() -> None:
    trajectory = harbor()
    trajectory["steps"][1]["observation"]["results"][0] = {
        "source_call_id": CALL_ID,
        "extra": {"is_error": True},
    }
    tool = to_wire(atif_to_messages(trajectory, prompt=INSTRUCTION))[2]
    assert tool["content"] == ""
    assert tool["error"] == "the tool call failed"


def test_text_parts_join_and_reasoning_only_steps_add_nothing() -> None:
    trajectory = harbor()
    trajectory["steps"][0]["message"] = [
        {"type": "text", "text": "Create hello.txt."},
        {"type": "text", "text": "Use Write."},
    ]
    trajectory["steps"][2]["message"] = ""
    trajectory["steps"][2]["reasoning_content"] = "Nothing left to do."
    messages = atif_to_messages(trajectory, prompt=INSTRUCTION)
    assert messages[0].content == "Create hello.txt.\n\nUse Write."
    assert [m.role for m in messages] == ["user", "assistant", "tool", "user"]


def edit(path: list[Any], value: Any) -> dict[str, Any]:
    trajectory = harbor()
    node: Any = trajectory
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return trajectory


RESULT = ["steps", 1, "observation", "results"]


@pytest.mark.parametrize(
    ("trajectory", "prompt", "error"),
    [
        (harbor(), None, "last message must be a user message"),
        ({"steps": []}, None, "last message must be a user message"),
        ({"schema_version": "ATIF-v1.7"}, INSTRUCTION, "no steps list"),
        (edit(RESULT, []), INSTRUCTION, "step 2: tool call .* has no result"),
        (
            edit([*RESULT, 0, "source_call_id"], None),
            INSTRUCTION,
            "step 2: observation result for None names no tool call",
        ),
        (
            edit(RESULT, HARBOR["steps"][1]["observation"]["results"] * 2),
            INSTRUCTION,
            "step 2: tool call .* has more than one result",
        ),
        (
            edit(["steps", 1, "tool_calls", 0, "tool_call_id"], ""),
            INSTRUCTION,
            "step 2: a tool call needs a tool_call_id",
        ),
        (
            edit(
                ["steps", 0, "message"],
                [
                    {"type": "text", "text": "Look at this"},
                    {
                        "type": "image",
                        "source": {"media_type": "image/png", "path": "a.png"},
                    },
                ],
            ),
            INSTRUCTION,
            "step 1: non-text content",
        ),
        (
            edit([*RESULT, 0, "content"], [{"type": "image"}]),
            INSTRUCTION,
            "step 2: non-text content",
        ),
        (edit(["steps", 0, "message"], ""), INSTRUCTION, "step 1: .* text"),
        (
            edit(["steps", 1, "tool_calls"], None),
            INSTRUCTION,
            "step 2: an observation result without a tool call",
        ),
        (
            edit(["steps", 0, "observation"], {"results": []}),
            INSTRUCTION,
            "step 1: a user step with tool calls or an observation",
        ),
        (
            edit(["steps", 0, "source"], "tool"),
            INSTRUCTION,
            "step 1: unknown step source 'tool'",
        ),
    ],
)
def test_what_messages_cannot_express_is_refused(
    trajectory: dict[str, Any], prompt: str | None, error: str
) -> None:
    with pytest.raises(AtifConversionError, match=error):
        atif_to_messages(trajectory, prompt=prompt)


def test_the_error_names_its_step() -> None:
    with pytest.raises(AtifConversionError) as caught:
        atif_to_messages(edit(RESULT, []), prompt=INSTRUCTION)
    assert caught.value.step_id == 2
    assert isinstance(caught.value, ValueError)


def test_harbors_example_is_valid_atif() -> None:
    ATIF_SCHEMA.validate(HARBOR)
