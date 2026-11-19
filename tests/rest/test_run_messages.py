"""``tasks.runs.create(messages=...)``: a run that opens its conversation
from ``ag_ui.core`` messages."""

from __future__ import annotations

import pytest
from ag_ui.core import (
    AssistantMessage,
    FunctionCall,
    Message,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from introspection_sdk._errors import ValidationError
from introspection_sdk.runner_resources.tasks import AsyncTasks, Tasks
from introspection_sdk.schemas.tasks import TaskRunCreateRequest, TaskRunKind

from .conftest import TASK_ID, FakeAPI, task_run_response

RUNS = f"/v1/tasks/{TASK_ID}/runs"

MESSAGES: list[Message] = [
    UserMessage(id="m1", content="List the files."),
    AssistantMessage(
        id="m2",
        content="Listing them.",
        tool_calls=[
            ToolCall(
                id="call-1",
                function=FunctionCall(name="bash", arguments='{"c":"ls"}'),
            )
        ],
    ),
    ToolMessage(id="m3", content="a.txt", tool_call_id="call-1"),
    UserMessage(id="m4", content="Now read a.txt."),
]

WIRE = [
    {"id": "m1", "role": "user", "content": "List the files."},
    {
        "id": "m2",
        "role": "assistant",
        "content": "Listing them.",
        "toolCalls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"c":"ls"}'},
            }
        ],
    },
    {"id": "m3", "role": "tool", "content": "a.txt", "toolCallId": "call-1"},
    {"id": "m4", "role": "user", "content": "Now read a.txt."},
]


def test_runs_create_sends_messages_in_camel_case(fake_api: FakeAPI):
    fake_api.add("POST", RUNS, json_body=task_run_response())
    handle = Tasks(fake_api.client()).runs.create(TASK_ID, messages=MESSAGES)
    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.path == RUNS
    assert fake_api.last_request.json() == {"messages": WIRE}
    assert handle.run.id == "run-1"


def test_runs_create_sends_dict_messages_as_given(fake_api: FakeAPI):
    fake_api.add("POST", RUNS, json_body=task_run_response())
    Tasks(fake_api.client()).runs.create(
        TASK_ID, messages=WIRE, kind="prompt", metadata={"source": "harbor"}
    )
    assert fake_api.last_request.json() == {
        "messages": WIRE,
        "kind": "prompt",
        "metadata": {"source": "harbor"},
    }


def test_a_failed_tool_result_sends_its_error(fake_api: FakeAPI):
    fake_api.add("POST", RUNS, json_body=task_run_response())
    failed = ToolMessage(
        id="m3", content="", tool_call_id="call-1", error="exit 1"
    )
    Tasks(fake_api.client()).runs.create(
        TASK_ID, messages=[*MESSAGES[:2], failed, MESSAGES[3]]
    )
    assert fake_api.last_request.json()["messages"][2] == {
        "id": "m3",
        "role": "tool",
        "content": "",
        "toolCallId": "call-1",
        "error": "exit 1",
    }


async def test_async_runs_create_sends_messages(fake_api: FakeAPI):
    fake_api.add("POST", RUNS, json_body=task_run_response())
    handle = await AsyncTasks(fake_api.async_client()).runs.create(
        TASK_ID, messages=MESSAGES
    )
    assert fake_api.last_request.json() == {"messages": WIRE}
    assert handle.run.task_id is not None


def test_runs_create_raises_the_servers_422(fake_api: FakeAPI):
    # The conversation is not empty, or the list breaks a server rule.
    fake_api.add(
        "POST",
        RUNS,
        status=422,
        json_body={
            "detail": "messages are only accepted while the task's "
            "conversation is empty"
        },
    )
    with pytest.raises(ValidationError) as caught:
        Tasks(fake_api.client()).runs.create(TASK_ID, messages=MESSAGES)
    assert caught.value.status_code == 422
    assert fake_api.last_request.json() == {"messages": WIRE}


@pytest.mark.parametrize(
    ("prompt", "kind"),
    [({"text": "hi"}, None), (None, "steer"), (None, TaskRunKind.STEER)],
)
def test_messages_refuse_a_prompt_or_a_steer(
    fake_api: FakeAPI, prompt: dict[str, str] | None, kind: str | None
):
    with pytest.raises(ValueError, match="messages"):
        Tasks(fake_api.client()).runs.create(
            TASK_ID, messages=MESSAGES, prompt=prompt, kind=kind
        )
    assert fake_api.requests == []


def test_the_request_model_reads_the_wire_shape():
    request = TaskRunCreateRequest.model_validate({"messages": WIRE})
    assert request.messages == MESSAGES
