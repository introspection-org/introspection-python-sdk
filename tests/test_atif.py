"""GenAI spans → ATIF.

Pure-unit tests of a projection: nothing here crosses a process or network
boundary. Every span is built as the JSON a conversation read returns and
validated into :class:`GenAiSpan`, because that boundary is how both callers
reach the projection. Every trajectory is validated against Harbor's own
schema (``fixtures/atif.schema.json``), which is what keeps the subset in
``schemas/atif.py`` from drifting away from the format's owner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from introspection_sdk.atif import AtifProjection, spans_to_atif
from introspection_sdk.schemas.atif import AtifStep, AtifTrajectory
from introspection_sdk.schemas.genai_span import GenAiSpan

ATIF_SCHEMA = Draft202012Validator(
    json.loads(
        (Path(__file__).parent / "fixtures/atif.schema.json").read_text()
    )
)


def dump(trajectory: AtifTrajectory) -> dict[str, Any]:
    """The trajectory as written, having passed Harbor's schema."""
    payload = trajectory.model_dump(mode="json")
    ATIF_SCHEMA.validate(payload)
    return payload


def text(role: str, content: str) -> dict[str, Any]:
    return {"role": role, "parts": [{"type": "text", "content": content}]}


def call(call_id: str | None, arguments: Any = None) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "tool_call", "name": "read"}
    if call_id is not None:
        part["id"] = call_id
    if arguments is not None:
        part["arguments"] = arguments
    return part


def result(call_id: str, response: Any = "ok") -> dict[str, Any]:
    return {
        "role": "tool",
        "parts": [
            {"type": "tool_call_response", "id": call_id, "response": response}
        ],
    }


def chat(
    second: int,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    *,
    usage: dict[str, Any] | None = None,
    cost: float | None = None,
    model: str = "claude-opus-5-5",
    agent: dict[str, Any] | None = None,
    system: str | None = None,
    new_messages_start: int | None = None,
) -> GenAiSpan:
    gen_ai: dict[str, Any] = {
        "operation": {"name": "chat"},
        "provider": {"name": "anthropic"},
        "conversation": {"id": "conv-1"},
        "response": {"model": model},
        "input": {"messages": inputs},
        "output": {"messages": outputs},
    }
    if usage is not None:
        gen_ai["usage"] = usage
    if cost is not None:
        gen_ai["cost"] = {"usd": cost}
    if agent is not None:
        gen_ai["agent"] = agent
    if system is not None:
        gen_ai["system_instructions"] = [{"type": "text", "content": system}]
    attributes: dict[str, Any] = {"gen_ai": gen_ai}
    if new_messages_start is not None:
        attributes["introspection"] = {
            "conversation": {"new_messages_start": new_messages_start}
        }
    return GenAiSpan.model_validate(
        {
            "trace_id": "t1",
            "span_id": f"chat-{second}",
            "start_time": f"2026-10-09T10:00:{second:02d}Z",
            "resource": {"service": {"name": "runtime", "version": "1.2.3"}},
            "attributes": attributes,
        }
    )


def tool(second: int, call_id: str, code: str) -> GenAiSpan:
    return GenAiSpan.model_validate(
        {
            "trace_id": "t1",
            "span_id": f"tool-{second}",
            "start_time": f"2026-10-09T10:00:{second:02d}Z",
            "status": {"code": code},
            "attributes": {
                "gen_ai": {
                    "operation": {"name": "execute_tool"},
                    "tool": {"name": "read", "call": {"id": call_id}},
                }
            },
        }
    )


USER = text("user", "Read the file")
FIRST_OUTPUT = {
    "role": "assistant",
    "parts": [
        {"type": "thinking", "content": "I should read it."},
        {"type": "text", "content": "Reading."},
        call("c1", {"path": "a.txt"}),
    ],
}
# The same message as it is sent back to the model: without the reasoning.
FIRST_OUTPUT_AS_INPUT = {
    "role": "assistant",
    "parts": [
        {"type": "text", "content": "Reading."},
        call("c1", {"path": "a.txt"}),
    ],
}
ANSWER = text("assistant", "It says hello.")


def whole_prompt_spans() -> list[GenAiSpan]:
    """Two model calls whose input is the whole prompt each time."""
    return [
        chat(
            1,
            [USER],
            [FIRST_OUTPUT],
            usage={
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read": {"input_tokens": 40},
            },
            cost=0.01,
            system="Be brief.",
        ),
        tool(2, "c1", "Ok"),
        chat(
            3,
            [USER, FIRST_OUTPUT_AS_INPUT, result("c1", "hello")],
            [ANSWER],
            usage={"input_tokens": 150, "output_tokens": 5},
            cost=0.02,
            system="Be brief.",
        ),
    ]


def test_a_model_call_becomes_one_agent_step_with_its_results() -> None:
    trajectory = dump(spans_to_atif(whole_prompt_spans()))

    assert trajectory == {
        "schema_version": "ATIF-v1.7",
        "session_id": "conv-1",
        "agent": {
            "name": "runtime",
            "version": "1.2.3",
            "model_name": "anthropic/claude-opus-5-5",
        },
        "steps": [
            {
                "step_id": 1,
                "timestamp": "2026-10-09T10:00:01Z",
                "source": "system",
                "message": "Be brief.",
            },
            {
                "step_id": 2,
                "timestamp": "2026-10-09T10:00:01Z",
                "source": "user",
                "message": "Read the file",
            },
            {
                "step_id": 3,
                "timestamp": "2026-10-09T10:00:01Z",
                "source": "agent",
                "model_name": "anthropic/claude-opus-5-5",
                "message": "Reading.",
                "reasoning_content": "I should read it.",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "read",
                        "arguments": {"path": "a.txt"},
                    }
                ],
                "observation": {
                    "results": [{"source_call_id": "c1", "content": "hello"}]
                },
                "metrics": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "cached_tokens": 40,
                    "cost_usd": 0.01,
                },
                "llm_call_count": 1,
            },
            {
                "step_id": 4,
                "timestamp": "2026-10-09T10:00:03Z",
                "source": "agent",
                "model_name": "anthropic/claude-opus-5-5",
                "message": "It says hello.",
                "metrics": {
                    "prompt_tokens": 150,
                    "completion_tokens": 5,
                    "cost_usd": 0.02,
                },
                "llm_call_count": 1,
            },
        ],
        "final_metrics": {
            "total_prompt_tokens": 250,
            "total_completion_tokens": 15,
            "total_cached_tokens": 40,
            "total_cost_usd": 0.03,
            "total_steps": 4,
        },
    }


def test_new_message_inputs_convert_the_same_as_whole_prompts() -> None:
    whole = whole_prompt_spans()
    deltas = [
        whole[0],
        whole[1],
        chat(
            3,
            [result("c1", "hello")],
            [ANSWER],
            usage={"input_tokens": 150, "output_tokens": 5},
            cost=0.02,
            system="Be brief.",
            new_messages_start=2,
        ),
    ]

    assert dump(spans_to_atif(deltas)) == dump(spans_to_atif(whole))


def test_a_newest_first_list_converts_the_same() -> None:
    spans = whole_prompt_spans()

    assert dump(spans_to_atif(reversed(spans))) == dump(spans_to_atif(spans))


def test_a_failed_tool_call_is_marked_on_its_result() -> None:
    spans = [
        chat(1, [USER], [{"role": "assistant", "parts": [call("failed")]}]),
        tool(2, "failed", "Error"),
        chat(
            3,
            [result("failed", "boom")],
            [{"role": "assistant", "parts": [call("passed")]}],
        ),
        tool(4, "passed", "Ok"),
        chat(
            5,
            [result("passed")],
            [{"role": "assistant", "parts": [call("unmarked")]}],
        ),
        chat(6, [result("unmarked")], [ANSWER]),
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert [
        step["observation"]["results"][0].get("extra")
        for step in steps
        if "observation" in step
    ] == [{"is_error": True}, None, None]


def test_known_tool_outcomes_need_no_tool_spans() -> None:
    projection = AtifProjection(tool_statuses={"c1": False})
    steps: list[AtifStep] = []
    for span in whole_prompt_spans():
        if span.span_id != "tool-2":
            steps.extend(projection.add(span))
    steps.extend(projection.finish())

    observation = steps[2].observation
    assert observation is not None
    assert observation.results[0].extra == {"is_error": True}


def test_a_step_is_held_until_its_results_have_been_read() -> None:
    spans = whole_prompt_spans()
    projection = AtifProjection()

    first = projection.add(spans[0])
    assert [step.source for step in first] == ["system", "user"]
    assert projection.add(spans[1]) == []
    second = projection.add(spans[2])
    assert [step.step_id for step in second] == [3, 4]
    assert projection.finish() == []

    streamed = projection.trajectory([*first, *second])
    assert dump(streamed) == dump(spans_to_atif(spans))


def test_a_retried_call_adds_no_steps() -> None:
    prompt = [USER, FIRST_OUTPUT_AS_INPUT, result("c1")]
    spans = [
        chat(1, [USER], [FIRST_OUTPUT]),
        chat(2, prompt, []),
        chat(3, prompt, [ANSWER]),
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert [step["source"] for step in steps] == ["user", "agent", "agent"]


def test_a_repeated_user_message_is_kept() -> None:
    again = text("user", "continue")
    spans = [
        chat(1, [again], [text("assistant", "One.")]),
        chat(2, [again], [text("assistant", "Two.")]),
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert [step["message"] for step in steps] == [
        "continue",
        "One.",
        "continue",
        "Two.",
    ]


def test_a_compacted_prompt_adds_the_summary_and_only_new_messages() -> None:
    summary = {
        "role": "user",
        "parts": [{"type": "compaction", "content": "Earlier: read a.txt."}],
    }
    kept = text("user", "Now b.txt")
    kept_answer = text("assistant", "On it.")
    new = text("user", "And c.txt")
    spans = [
        chat(1, [USER], [text("assistant", "Done.")]),
        chat(2, [USER, text("assistant", "Done."), kept], [kept_answer]),
        chat(3, [summary, kept, kept_answer, new], [ANSWER]),
        chat(4, [summary, kept, kept_answer, new, ANSWER, USER], [ANSWER]),
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert [step["message"] for step in steps] == [
        "Read the file",
        "Done.",
        "Now b.txt",
        "On it.",
        "Earlier: read a.txt.",
        "And c.txt",
        "It says hello.",
        "Read the file",
        "It says hello.",
    ]


def test_each_agent_keeps_its_own_prompt_history() -> None:
    root = {"id": "root-agent", "name": "agent"}
    child = {"name": "researcher"}
    spans = [
        chat(1, [USER], [text("assistant", "Root.")], agent=root),
        chat(2, [USER], [text("assistant", "Child.")], agent=child),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert [step["message"] for step in trajectory["steps"]] == [
        "Read the file",
        "Root.",
        "Read the file",
        "Child.",
    ]
    assert trajectory["agent"]["name"] == "agent"


def test_history_read_only_as_input_becomes_agent_steps_without_usage() -> (
    None
):
    spans = [
        chat(
            1,
            [
                text("system", "Be brief."),
                USER,
                FIRST_OUTPUT_AS_INPUT,
                result("c1", {"text": "hello"}),
            ],
            [ANSWER],
            usage={"input_tokens": 7, "output_tokens": 1},
        )
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert [step["source"] for step in steps] == [
        "system",
        "user",
        "agent",
        "agent",
    ]
    assert "metrics" not in steps[2] and "llm_call_count" not in steps[2]
    assert steps[2]["observation"]["results"] == [
        {"source_call_id": "c1", "content": '{"text": "hello"}'}
    ]


def test_a_result_without_a_read_call_stands_alone() -> None:
    spans = [
        tool(1, "lost", "Error"),
        chat(2, [result("lost", "late")], [ANSWER]),
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert steps[0] == {
        "step_id": 1,
        "timestamp": "2026-10-09T10:00:02Z",
        "source": "system",
        "message": "",
        "observation": {
            "results": [
                {
                    "content": "late",
                    "extra": {"tool_call_id": "lost", "is_error": True},
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (None, {}),
        ('{"path": "a.txt"}', {"path": "a.txt"}),
        ("not json", {"_raw": "not json"}),
        ("[1]", {"_raw": "[1]"}),
        (7, {"_raw": 7}),
    ],
)
def test_tool_arguments_are_always_an_object(
    arguments: Any, expected: dict[str, Any]
) -> None:
    spans = [
        chat(
            1,
            [USER],
            [{"role": "assistant", "parts": [call("c1", arguments)]}],
        )
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert steps[1]["tool_calls"][0]["arguments"] == expected


def test_non_text_parts_are_omitted_and_noted() -> None:
    image = {"type": "blob", "content": "aGk=", "mime_type": "image/png"}
    spans = [
        chat(
            1,
            [{"role": "user", "parts": [image, USER["parts"][0]]}],
            [{"role": "assistant", "parts": [image, ANSWER["parts"][0]]}],
        )
    ]

    trajectory = dump(spans_to_atif(spans))

    assert [step["message"] for step in trajectory["steps"]] == [
        "Read the file",
        "It says hello.",
    ]
    assert trajectory["notes"].startswith("2 non-text message part(s)")


def test_two_observed_models_leave_the_agent_model_unset() -> None:
    spans = [
        chat(1, [USER], [text("assistant", "One.")], model="a"),
        chat(2, [USER], [text("assistant", "Two.")], model="b"),
    ]

    trajectory = dump(
        spans_to_atif(
            spans,
            session_id="trial-7",
            agent_name="introspection-recipe",
            agent_version="0.9.0",
        )
    )

    assert trajectory["session_id"] == "trial-7"
    assert trajectory["agent"] == {
        "name": "introspection-recipe",
        "version": "0.9.0",
    }
    assert [step.get("model_name") for step in trajectory["steps"]] == [
        None,
        "anthropic/a",
        None,
        "anthropic/b",
    ]


def test_a_span_without_resource_or_provider_falls_back() -> None:
    span = GenAiSpan.model_validate(
        {
            "trace_id": "t1",
            "start_time": "2026-10-09T10:00:01Z",
            "resource": {"service.name": "plugin"},
            "attributes": {
                "gen_ai": {
                    "request": {"model": "m"},
                    "input": {"messages": [USER]},
                    "output": {"messages": [ANSWER]},
                }
            },
        }
    )
    bare = GenAiSpan.model_validate(
        {"trace_id": "t1", "start_time": "2026-10-09T10:00:00Z"}
    )

    trajectory = dump(spans_to_atif([bare, span]))

    assert trajectory["agent"] == {
        "name": "plugin",
        "version": "unknown",
        "model_name": "m",
    }
    assert "session_id" not in trajectory


def test_a_model_call_that_returned_no_content_is_still_a_step() -> None:
    # The read omits empty containers, so the message arrives without parts.
    spans = [
        chat(
            1,
            [USER],
            [{"role": "assistant", "finish_reason": "stop"}],
            usage={"input_tokens": 9, "output_tokens": 4},
        )
    ]

    steps = dump(spans_to_atif(spans))["steps"]

    assert steps[1] == {
        "step_id": 2,
        "timestamp": "2026-10-09T10:00:01Z",
        "source": "agent",
        "model_name": "anthropic/claude-opus-5-5",
        "message": "",
        "metrics": {"prompt_tokens": 9, "completion_tokens": 4},
        "llm_call_count": 1,
    }


def test_a_tool_call_without_an_id_is_refused() -> None:
    spans = [
        chat(1, [USER], [{"role": "assistant", "parts": [call(None)]}]),
    ]

    with pytest.raises(ValueError, match="without an id"):
        spans_to_atif(spans)


def test_spans_without_messages_are_refused() -> None:
    with pytest.raises(ValueError, match="no message"):
        spans_to_atif([tool(1, "c1", "Ok")])
