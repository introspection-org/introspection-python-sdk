"""GenAI spans → ATIF.

Pure-unit tests of a projection: nothing here crosses a process or network
boundary. Every span is built as the JSON a conversation read returns and
validated into :class:`GenAiSpan`, because that boundary is how both callers
reach the projection. Every trajectory is validated against Harbor's own
schema (``fixtures/atif.schema.json``), which is what keeps the subset in
``schemas/atif.py`` from drifting away from the format's owner. The schema
cannot express the cross-field rules of Harbor's ``Trajectory`` model, so
``dump`` checks the ones the projection could break.
"""

from __future__ import annotations

import gc
import json
import weakref
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
    for number, step in enumerate(payload["steps"], start=1):
        assert step["step_id"] == number
        calls = {call["tool_call_id"] for call in step.get("tool_calls", [])}
        for item in step.get("observation", {}).get("results", []):
            source = item.get("source_call_id")
            assert source is None or source in calls
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
            "history": {"new_messages": {"start": new_messages_start}}
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


def tool(
    second: int, call_id: str, code: str, output: Any = None
) -> GenAiSpan:
    call: dict[str, Any] = {"id": call_id}
    if output is not None:
        call["result"] = output
    return GenAiSpan.model_validate(
        {
            "trace_id": "t1",
            "span_id": f"tool-{second}",
            "start_time": f"2026-10-09T10:00:{second:02d}Z",
            "status": {"code": code},
            "attributes": {
                "gen_ai": {
                    "operation": {"name": "execute_tool"},
                    "tool": {"name": "read", "call": call},
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


DETAILS = {"message": 3, "reply": "the whole reply", "absent": None}
# What the Pi span writer records: the tool result, stringified.
PI_RESULT = json.dumps(
    {"content": [{"type": "text", "text": "hello"}], "details": DETAILS}
)
ASKED = {"role": "assistant", "parts": [call("c1")]}


def results(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for step in trajectory["steps"]
        for item in step.get("observation", {}).get("results", [])
    ]


def streamed(
    spans: list[GenAiSpan], *, tool_statuses: dict[str, bool] | None = None
) -> dict[str, Any]:
    """The trajectory as a streaming reader assembles it."""
    projection = AtifProjection(tool_statuses=tool_statuses)
    steps: list[AtifStep] = []
    for span in spans:
        steps.extend(projection.add(span))
    steps.extend(projection.finish())
    return dump(projection.trajectory(steps))


def test_a_tool_span_result_is_kept_beside_the_content() -> None:
    spans = [
        chat(1, [USER], [ASKED]),
        tool(2, "c1", "Ok", PI_RESULT),
        chat(3, [result("c1", "what the model read")], [ANSWER]),
    ]

    assert results(dump(spans_to_atif(spans))) == [
        {
            "source_call_id": "c1",
            "content": "what the model read",
            "extra": {"details": DETAILS},
        }
    ]


def test_an_error_result_keeps_its_details() -> None:
    spans = [
        chat(1, [USER], [ASKED]),
        tool(2, "c1", "Error", PI_RESULT),
        chat(3, [result("c1", "boom")], [ANSWER]),
    ]

    assert results(dump(spans_to_atif(spans))) == [
        {
            "source_call_id": "c1",
            "content": "boom",
            "extra": {"is_error": True, "details": DETAILS},
        }
    ]


@pytest.mark.parametrize(
    ("output", "content", "extra"),
    [
        pytest.param("plain text", "plain text", None, id="plain-string"),
        pytest.param("", None, None, id="empty-string"),
        pytest.param("7", "7", None, id="json-scalar-string"),
        pytest.param(
            '{"rows": 2}', '{"rows": 2}', {"details": {"rows": 2}}, id="string"
        ),
        pytest.param(
            {"rows": 2}, '{"rows": 2}', {"details": {"rows": 2}}, id="object"
        ),
        pytest.param("[1]", "[1]", {"details": [1]}, id="array-string"),
        pytest.param(
            {"content": "not parts", "rows": 2},
            '{"content": "not parts", "rows": 2}',
            {"details": {"content": "not parts", "rows": 2}},
            id="object-with-a-content-key",
        ),
        pytest.param(
            {"content": [{"type": "text", "text": "a"}], "details": {"k": 1}},
            "a",
            {"details": {"k": 1}},
            id="envelope-object",
        ),
        pytest.param(
            {"content": [{"type": "text", "text": "a"}]},
            "a",
            None,
            id="envelope-without-details",
        ),
        pytest.param(
            {"content": [], "details": {"k": 1}},
            None,
            {"details": {"k": 1}},
            id="envelope-without-content",
        ),
        pytest.param(
            {"content": "a", "details": {"k": 1}},
            "a",
            {"details": {"k": 1}},
            id="envelope-with-string-content",
        ),
        pytest.param(
            {"content": [{"type": "image", "data": "aGk="}], "isError": False},
            '[{"type": "image", "data": "aGk="}]',
            None,
            id="envelope-with-an-image",
        ),
    ],
)
def test_a_result_reads_as_text_and_details(
    output: Any, content: str | None, extra: dict[str, Any] | None
) -> None:
    trailing = results(
        dump(
            spans_to_atif(
                [chat(1, [USER], [ASKED]), tool(2, "c1", "Ok", output)]
            )
        )
    )
    matched = results(
        dump(
            spans_to_atif(
                [
                    chat(1, [USER], [ASKED]),
                    tool(2, "c1", "Ok", output),
                    chat(3, [result("c1", "read")], [ANSWER]),
                ]
            )
        )
    )

    expected = {"source_call_id": "c1", "content": content, "extra": extra}
    if content is None and extra is None:
        assert trailing == []
    else:
        assert trailing == [
            {
                key: value
                for key, value in expected.items()
                if value is not None
            }
        ]
    assert matched[0]["content"] == "read"
    assert matched[0].get("extra") == extra


def test_a_last_tool_call_becomes_a_result_without_a_later_chat() -> None:
    spans = [chat(1, [USER], [ASKED]), tool(2, "c1", "Ok", PI_RESULT)]

    trajectory = dump(spans_to_atif(spans))

    assert trajectory["steps"][-1]["source"] == "agent"
    assert results(trajectory) == [
        {
            "source_call_id": "c1",
            "content": "hello",
            "extra": {"details": DETAILS},
        }
    ]
    assert trajectory["final_metrics"]["total_steps"] == 2


def test_a_last_failed_tool_call_is_marked_without_a_result() -> None:
    spans = [chat(1, [USER], [ASKED]), tool(2, "c1", "Error")]

    assert results(dump(spans_to_atif(spans))) == [
        {"source_call_id": "c1", "extra": {"is_error": True}}
    ]


def test_a_tool_span_saying_nothing_adds_no_result() -> None:
    spans = [chat(1, [USER], [ASKED]), tool(2, "c1", "Ok")]

    assert results(dump(spans_to_atif(spans))) == []


def test_a_result_the_next_prompt_leaves_out_comes_from_the_tool_span() -> (
    None
):
    spans = [
        chat(1, [USER], [ASKED]),
        tool(2, "c1", "Ok", PI_RESULT),
        chat(3, [text("user", "Go on.")], [ANSWER]),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert results(trajectory) == [
        {
            "source_call_id": "c1",
            "content": "hello",
            "extra": {"details": DETAILS},
        }
    ]
    assert [step["message"] for step in trajectory["steps"]] == [
        "Read the file",
        "",
        "Go on.",
        "It says hello.",
    ]


def test_no_tool_span_result_leaves_the_output_as_it_was() -> None:
    spans = whole_prompt_spans()
    without = [span for span in spans if span.span_id != "tool-2"]

    trajectory = dump(spans_to_atif(without))

    assert results(trajectory) == [
        {"source_call_id": "c1", "content": "hello"}
    ]
    assert dump(spans_to_atif(spans)) == trajectory


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(("tool", "asked", "answered"), id="before-the-call"),
        pytest.param(("asked", "tool", "answered"), id="between"),
        pytest.param(("asked", "answered", "tool"), id="after-the-result"),
    ],
)
@pytest.mark.parametrize("code", ["Ok", "Error"])
def test_a_tool_span_reaches_its_result_in_any_order(
    order: tuple[str, str, str], code: str
) -> None:
    seconds = {name: second for second, name in enumerate(order, start=1)}
    spans = [
        chat(seconds["asked"], [USER], [ASKED]),
        chat(seconds["answered"], [result("c1", "read")], [ANSWER]),
        tool(seconds["tool"], "c1", code, PI_RESULT),
    ]

    extra = {"details": DETAILS} | (
        {"is_error": True} if code == "Error" else {}
    )
    expected = [{"source_call_id": "c1", "content": "read", "extra": extra}]
    assert results(dump(spans_to_atif(spans))) == expected
    # A caller that knows the outcomes also knows which spans are still to come.
    in_order = sorted(spans, key=lambda span: span.start_time)
    assert (
        results(streamed(in_order, tool_statuses={"c1": code == "Ok"}))
        == expected
    )


def test_a_step_known_to_have_a_tool_span_waits_for_it() -> None:
    projection = AtifProjection(tool_statuses={"c1": True})

    assert [
        step.source for step in projection.add(chat(1, [USER], [ASKED]))
    ] == ["user"]
    assert projection.add(chat(2, [result("c1", "read")], [ANSWER])) == []

    settled = projection.add(tool(3, "c1", "Ok", PI_RESULT))

    assert [step.step_id for step in settled] == [2, 3]
    observation = settled[0].observation
    assert observation is not None
    assert observation.results[0].extra == {"details": DETAILS}


def test_a_known_tool_span_saying_nothing_still_releases_its_step() -> None:
    projection = AtifProjection(tool_statuses={"c1": True})
    projection.add(chat(1, [USER], [ASKED]))
    projection.add(chat(2, [result("c1")], [ANSWER]))

    settled = projection.add(tool(3, "c1", "Ok"))

    assert [step.step_id for step in settled] == [2, 3]


def test_a_known_tool_span_that_never_comes_releases_at_the_end() -> None:
    spans = [chat(1, [USER], [ASKED]), chat(2, [result("c1")], [ANSWER])]

    trajectory = streamed(spans, tool_statuses={"c1": True})

    assert results(trajectory) == [{"source_call_id": "c1", "content": "ok"}]


def test_a_known_tool_span_after_a_prompt_without_the_result_still_lands() -> (
    None
):
    spans = [
        chat(1, [USER], [ASKED]),
        chat(2, [text("user", "Go on.")], [ANSWER]),
        tool(3, "c1", "Ok", PI_RESULT),
    ]

    assert results(streamed(spans, tool_statuses={"c1": True})) == [
        {
            "source_call_id": "c1",
            "content": "hello",
            "extra": {"details": DETAILS},
        }
    ]
    assert results(dump(spans_to_atif(spans))) == results(
        streamed(spans, tool_statuses={"c1": True})
    )


def test_a_tool_span_after_its_step_was_returned_stands_alone() -> None:
    projection = AtifProjection()
    steps: list[AtifStep] = []
    for span in [chat(1, [USER], [ASKED]), chat(2, [result("c1")], [ANSWER])]:
        steps.extend(projection.add(span))
    assert [step.step_id for step in steps] == [1, 2, 3]

    steps.extend(projection.add(tool(3, "c1", "Error", PI_RESULT)))
    steps.extend(projection.finish())

    trajectory = dump(projection.trajectory(steps))
    assert trajectory["steps"][3] == {
        "step_id": 4,
        "timestamp": "2026-10-09T10:00:03Z",
        "source": "system",
        "message": "",
        "observation": {
            "results": [
                {
                    "content": "hello",
                    "extra": {
                        "tool_call_id": "c1",
                        "is_error": True,
                        "details": DETAILS,
                    },
                }
            ]
        },
    }


def test_a_returned_step_is_not_kept_for_a_late_tool_span() -> None:
    projection = AtifProjection()
    steps = [
        step
        for span in [
            chat(1, [USER], [ASKED]),
            chat(2, [result("c1")], [ANSWER]),
        ]
        for step in projection.add(span)
    ]
    released = next(step for step in steps if step.tool_calls)
    reference = weakref.ref(released)

    del released, steps
    gc.collect()

    assert reference() is None


def test_a_late_tool_span_with_only_text_adds_nothing_to_a_returned_step() -> (
    None
):
    spans = [chat(1, [USER], [ASKED]), chat(2, [result("c1")], [ANSWER])]
    projection = AtifProjection()
    steps = [step for span in spans for step in projection.add(span)]

    steps.extend(projection.add(tool(3, "c1", "Ok", "plain text")))
    steps.extend(projection.finish())

    assert [step.step_id for step in steps] == [1, 2, 3]


def test_a_late_tool_span_merges_while_another_call_holds_the_step() -> None:
    both = {"role": "assistant", "parts": [call("c1"), call("c2")]}
    spans = [
        chat(1, [USER], [both]),
        chat(2, [result("c1", "one")], [ANSWER]),
        tool(3, "c1", "Ok", PI_RESULT),
        tool(4, "c2", "Ok", {"rows": 2}),
    ]

    # c2 is expected, so the step is still held when c1's span arrives.
    trajectory = streamed(spans, tool_statuses={"c2": True})

    assert results(trajectory) == [
        {
            "source_call_id": "c1",
            "content": "one",
            "extra": {"details": DETAILS},
        },
        {
            "source_call_id": "c2",
            "content": '{"rows": 2}',
            "extra": {"details": {"rows": 2}},
        },
    ]


def test_several_tool_calls_of_one_step_each_get_their_details() -> None:
    both = {"role": "assistant", "parts": [call("c1"), call("c2"), call("c3")]}
    spans = [
        chat(1, [USER], [both]),
        tool(2, "c1", "Ok", {"n": 1}),
        tool(3, "c2", "Error", {"n": 2}),
        tool(4, "c3", "Ok", {"n": 3}),
        chat(5, [result("c1", "one"), result("c2", "two")], [ANSWER]),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert trajectory["steps"][1]["observation"]["results"] == [
        {
            "source_call_id": "c1",
            "content": "one",
            "extra": {"details": {"n": 1}},
        },
        {
            "source_call_id": "c2",
            "content": "two",
            "extra": {"is_error": True, "details": {"n": 2}},
        },
        {
            "source_call_id": "c3",
            "content": '{"n": 3}',
            "extra": {"details": {"n": 3}},
        },
    ]


def test_each_lane_keeps_its_own_results() -> None:
    root = {"id": "root-agent", "name": "agent"}
    child = {"id": "child-agent", "name": "researcher"}
    spans = [
        chat(1, [USER], [ASKED], agent=root),
        chat(
            2,
            [USER],
            [{"role": "assistant", "parts": [call("c2")]}],
            agent=child,
        ),
        tool(3, "c2", "Ok", {"who": "child"}),
        tool(4, "c1", "Ok", {"who": "root"}),
        chat(5, [result("c2", "two")], [ANSWER], agent=child),
    ]

    trajectory = dump(spans_to_atif(spans))

    by_call = {
        call["tool_call_id"]: step["observation"]["results"]
        for step in trajectory["steps"]
        for call in step.get("tool_calls", [])
    }
    assert by_call == {
        "c1": [
            {
                "source_call_id": "c1",
                "content": '{"who": "root"}',
                "extra": {"details": {"who": "root"}},
            }
        ],
        "c2": [
            {
                "source_call_id": "c2",
                "content": "two",
                "extra": {"details": {"who": "child"}},
            }
        ],
    }


def test_a_result_without_a_read_call_keeps_its_details() -> None:
    spans = [
        tool(1, "lost", "Ok", PI_RESULT),
        chat(2, [result("lost", "late")], [ANSWER]),
    ]

    assert results(dump(spans_to_atif(spans))) == [
        {
            "content": "late",
            "extra": {"tool_call_id": "lost", "details": DETAILS},
        }
    ]


def test_a_tool_span_whose_call_was_never_read_comes_last() -> None:
    spans = [
        tool(1, "lost", "Ok", PI_RESULT),
        chat(2, [USER], [ANSWER]),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert [step["message"] for step in trajectory["steps"]] == [
        "Read the file",
        "It says hello.",
        "",
    ]
    assert trajectory["steps"][2] == {
        "step_id": 3,
        "timestamp": "2026-10-09T10:00:01Z",
        "source": "system",
        "message": "",
        "observation": {
            "results": [
                {
                    "content": "hello",
                    "extra": {"tool_call_id": "lost", "details": DETAILS},
                }
            ]
        },
    }
    assert trajectory["final_metrics"]["total_steps"] == 3


def test_tool_spans_alone_are_still_refused() -> None:
    with pytest.raises(ValueError, match="no message"):
        spans_to_atif([tool(1, "c1", "Ok", PI_RESULT)])


def test_a_reused_call_id_answers_its_own_step() -> None:
    spans = [
        chat(1, [USER], [ASKED]),
        chat(2, [result("c1", "first")], [ASKED]),
        tool(3, "c1", "Ok", {"n": 2}),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert [
        step["observation"]["results"]
        for step in trajectory["steps"]
        if "observation" in step
    ] == [
        [{"source_call_id": "c1", "content": "first"}],
        [
            {
                "source_call_id": "c1",
                "content": '{"n": 2}',
                "extra": {"details": {"n": 2}},
            }
        ],
    ]


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


def test_a_total_some_model_call_did_not_report_is_left_unset() -> None:
    spans = [
        chat(
            1,
            [USER],
            [FIRST_OUTPUT],
            usage={"input_tokens": 100, "output_tokens": 10},
            cost=0.01,
        ),
        # This call reported neither usage nor cost.
        chat(3, [result("c1", "hello")], [ANSWER]),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert trajectory["final_metrics"] == {"total_steps": 3}
    assert trajectory["steps"][1]["metrics"] == {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "cost_usd": 0.01,
    }


def test_totals_every_model_call_reported_are_summed() -> None:
    spans = [
        chat(
            1,
            [USER],
            [FIRST_OUTPUT],
            usage={"input_tokens": 100, "output_tokens": 10},
        ),
        chat(
            3,
            [result("c1", "hello")],
            [ANSWER],
            usage={"input_tokens": 150, "output_tokens": 5},
        ),
    ]

    # Usage without cached tokens read none from the cache; a cost no call
    # reported is not known.
    assert dump(spans_to_atif(spans))["final_metrics"] == {
        "total_prompt_tokens": 250,
        "total_completion_tokens": 15,
        "total_cached_tokens": 0,
        "total_steps": 3,
    }


def test_a_model_call_that_used_no_tokens_cost_nothing() -> None:
    spans = [
        chat(
            1,
            [USER],
            [FIRST_OUTPUT],
            usage={"input_tokens": 100, "output_tokens": 10},
            cost=0.01,
        ),
        # A failed call: the read omits its zero cost.
        chat(
            3,
            [result("c1", "hello")],
            [text("assistant", "")],
            usage={"input_tokens": 0, "output_tokens": 0},
        ),
    ]

    trajectory = dump(spans_to_atif(spans))

    assert trajectory["final_metrics"]["total_cost_usd"] == 0.01
    assert "cost_usd" not in trajectory["steps"][2]["metrics"]


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
