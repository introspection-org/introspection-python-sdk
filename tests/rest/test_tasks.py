"""Tests for ``runner.tasks`` (:mod:`introspection_sdk.runner_resources.tasks`)."""

from __future__ import annotations

from introspection_sdk.runner_resources.tasks import RunHandle, Tasks
from introspection_sdk.schemas.tasks import TaskMode, TaskPrompt

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
    page = _tasks(fake_api).list(statuses=["pending"], modes=["agent"])
    assert str(page.records[0].id) == TASK_ID
    params = fake_api.last_request.params
    assert params.get_list("statuses") == ["pending"]
    assert params.get("modes") == "agent"


def test_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks", json_body=paginated([task_payload()]))
    assert len(list(_tasks(fake_api).list())) == 1


def test_create_serialises_mode_enum(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    res = _tasks(fake_api).create(
        prompt="hello", mode=TaskMode.INTROSPECT, metadata=None
    )
    assert str(res.task.id) == TASK_ID
    body = fake_api.last_request.json()
    assert body["mode"] == "introspect"
    assert "metadata" not in body  # None dropped


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


def test_runs_get(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}/runs/run-1",
        json_body=task_run_payload(status="completed"),
    )
    run = _tasks(fake_api).runs.get(TASK_ID, "run-1")
    assert run.status.value == "completed"


def test_run_handle_cancel(fake_api: FakeAPI):
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
    assert handle.cancel().id == "run-1"


def test_run_handle_stream_and_text(fake_api: FakeAPI):
    sse = "event: text\ndata: hel\n\nevent: text\ndata: lo\n\n"
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
    assert [e.data for e in events] == ["hel", "lo"]
    # text() re-streams and concatenates text/message frames.
    assert handle.text() == "hello"
