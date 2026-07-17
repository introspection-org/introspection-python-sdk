"""Tests for ``runner.tasks`` (:mod:`introspection_sdk.runner_resources.tasks`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from introspection_sdk.runner_resources.tasks import RunHandle, Tasks
from introspection_sdk.schemas.agui import ResumeEntry
from introspection_sdk.schemas.tasks import (
    Task,
    TaskPrompt,
    TaskRunKind,
)

from .conftest import (
    TASK_ID,
    FakeAPI,
    paginated,
    task_cancel_response,
    task_create_response,
    task_payload,
    task_run_payload,
    task_run_response,
)


def _tasks(fake_api: FakeAPI) -> Tasks:
    return Tasks(fake_api.client())


def test_list_with_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks", json_body=paginated([task_payload()]))
    page = _tasks(fake_api).list(
        statuses=["pending"],
        updated_after=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert str(page.records[0].id) == TASK_ID
    params = fake_api.last_request.params
    assert params.get_list("statuses") == ["pending"]
    assert params.get("updated_after") == "2026-01-01T00:00:00+00:00"


def test_task_response_does_not_surface_internal_kind():
    payload = task_payload().model_dump(mode="json")
    payload["kind"] = "process"
    task = Task.model_validate(payload)
    assert not hasattr(task, "kind")
    assert "kind" not in task.model_dump()


def test_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks", json_body=paginated([task_payload()]))
    assert len(list(_tasks(fake_api).list())) == 1


def test_create_omits_internal_task_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    res = _tasks(fake_api).create(prompt="hello", metadata=None)
    assert str(res.task.id) == TASK_ID
    body = fake_api.last_request.json()
    assert "mode" not in body
    assert "kind" not in body
    assert "system_id" not in body
    assert "metadata" not in body  # None dropped


def test_create_sends_idle_timeout_and_fork_share_id(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    _tasks(fake_api).create(
        prompt="hello",
        idle_timeout_seconds=0,
        fork_share_id="share-123",
    )
    body = fake_api.last_request.json()
    assert body["idle_timeout_seconds"] == 0  # 0 is meaningful, not dropped
    assert body["fork_share_id"] == "share-123"


def test_start_forwards_idle_timeout(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    _tasks(fake_api).start(prompt="go", idle_timeout_seconds=120)
    body = fake_api.last_request.json()
    assert body["idle_timeout_seconds"] == 120
    assert "visibility" not in body


def test_get(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/tasks/{TASK_ID}", json_body=task_payload())
    assert _tasks(fake_api).get(TASK_ID).title == "Summarize repo"


def test_update(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/tasks/{TASK_ID}",
        json_body=task_payload(title="renamed", is_archived=True),
    )
    task = _tasks(fake_api).update(
        TASK_ID, title="renamed", is_archived=True, metadata={"k": "v"}
    )
    assert task.title == "renamed"
    body = fake_api.last_request.json()
    assert body == {
        "title": "renamed",
        "is_archived": True,
        "metadata": {"k": "v"},
    }


def test_delete_archive_unarchive(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/tasks/{TASK_ID}", status=204)
    fake_api.add("POST", f"/v1/tasks/{TASK_ID}/archive", status=204)
    fake_api.add("POST", f"/v1/tasks/{TASK_ID}/unarchive", status=204)
    tasks = _tasks(fake_api)
    assert tasks.delete(TASK_ID) is None
    assert tasks.archive(TASK_ID) is None
    assert tasks.unarchive(TASK_ID) is None


def test_start_returns_run_handle(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    handle = _tasks(fake_api).start(prompt="go")
    assert isinstance(handle, RunHandle)
    assert handle.run.id == "run-1"
    assert handle.task is not None


def test_runs_create_with_prompt_model(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    handle = _tasks(fake_api).runs.create(
        TASK_ID, prompt=TaskPrompt(text="hi")
    )
    assert handle.task is None
    assert fake_api.last_request.json()["prompt"] == {"text": "hi"}


def test_runs_create_with_message(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    _tasks(fake_api).runs.create(TASK_ID, message="ping")
    assert fake_api.last_request.json() == {"message": "ping"}


def test_runs_create_with_kind_and_metadata(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    _tasks(fake_api).runs.create(
        TASK_ID,
        message="revise",
        kind=TaskRunKind.STEER,
        metadata={"source": "test"},
    )
    assert fake_api.last_request.json() == {
        "message": "revise",
        "kind": "steer",
        "metadata": {"source": "test"},
    }


def test_runs_resume_posts_ag_ui_resume_entries(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    handle = _tasks(fake_api).runs.resume(
        TASK_ID,
        resume=[
            ResumeEntry(interrupt_id="interrupt-1", status="resolved"),
            {
                "interruptId": "interrupt-2",
                "status": "cancelled",
                "payload": {"reason": "skip"},
            },
        ],
    )
    assert handle.run.id == "run-1"
    assert fake_api.last_request.json() == {
        "resume": [
            {"interruptId": "interrupt-1", "status": "resolved"},
            {
                "interruptId": "interrupt-2",
                "status": "cancelled",
                "payload": {"reason": "skip"},
            },
        ]
    }


def test_tasks_does_not_expose_resume(fake_api: FakeAPI):
    assert not hasattr(_tasks(fake_api), "resume")


def test_runs_get(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}/runs/run-1",
        json_body=task_run_payload(status="completed"),
    )
    run = _tasks(fake_api).runs.get(TASK_ID, "run-1")
    assert run.status.value == "completed"


def test_run_handle_abort_and_drain(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs/run-1/cancel",
        json_body=task_cancel_response("run-1"),
    )
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    handle = _tasks(fake_api).runs.create(TASK_ID, message="x")
    assert handle.abort().id == "run-1"
    assert fake_api.last_request.json() == {"mode": "abort"}
    assert handle.drain(within_seconds=60).id == "run-1"
    assert fake_api.last_request.json() == {
        "mode": "drain",
        "drain_within_seconds": 60,
    }
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        handle.drain(within_seconds=-1)


def test_run_handle_stream_and_text(fake_api: FakeAPI):
    sse = (
        'event: ag_ui\ndata: {"type":"TEXT_MESSAGE_CONTENT",'
        '"messageId":"msg-1","delta":"hel"}\n\n'
        'event: ag_ui\ndata: {"type":"TEXT_MESSAGE_CHUNK",'
        '"messageId":"msg-1","delta":"lo"}\n\n'
    )
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs",
        json_body=task_run_response(),
    )
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}/runs/run-1/stream",
        content=sse.encode(),
    )
    handle = _tasks(fake_api).runs.create(TASK_ID, message="x")
    events = list(handle.stream())
    assert [
        e.model_dump(exclude_none=True, by_alias=True)["delta"] for e in events
    ] == ["hel", "lo"]
    # text() re-streams and concatenates AG-UI text deltas.
    assert handle.text() == "hello"
