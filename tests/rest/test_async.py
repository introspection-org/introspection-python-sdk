"""Tests for the async REST / Runner surface.

The async twin of the sync contract tests: same in-process
``httpx.MockTransport`` route table (see ``conftest.FakeAPI``), driven
through the ``Async*`` namespaces. Nothing in ``introspection_sdk`` is
patched or stubbed. ``asyncio_mode = "auto"`` (pyproject) means the
``async def test_*`` functions run without an explicit marker.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from introspection_sdk._errors import IntrospectionAPIError
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.resources.experiments import AsyncExperiments
from introspection_sdk.resources.runtimes import AsyncRuntimes
from introspection_sdk.runner import AsyncRunner
from introspection_sdk.runner_resources import (
    AsyncFiles,
    AsyncRunHandle,
    AsyncTasks,
)
from introspection_sdk.schemas.agui import ResumeEntry
from introspection_sdk.schemas.runner import RunnerSpec
from introspection_sdk.schemas.tasks import TaskRunKind
from introspection_sdk.streaming import parse_ag_ui_events_async

from .conftest import (
    EXPERIMENT_ID,
    FILE_ID,
    RUNTIME_ID,
    TASK_ID,
    FakeAPI,
    experiment_payload,
    file_payload,
    paginated,
    runner_spec_payload,
    runtime_payload,
    task_cancel_response,
    task_create_response,
    task_payload,
    task_run_response,
)


def _spec(**over):
    return runner_spec_payload(**over)


# --- _AsyncHttpClient ------------------------------------------------


async def test_http_request_and_error(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks/" + TASK_ID, json_body=task_payload())
    fake_api.add("GET", "/v1/tasks/missing", status=404, json_body={})
    http = fake_api.async_client()
    try:
        payload = await http.request("GET", f"/v1/tasks/{TASK_ID}")
        assert payload["id"] == TASK_ID
        with pytest.raises(IntrospectionAPIError):
            await http.request("GET", "/v1/tasks/missing")
    finally:
        await http.aclose()


async def test_http_stream_bytes(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/files/{FILE_ID}/content", content=b"chunk-data")
    http = fake_api.async_client()
    try:
        chunks = [
            c async for c in http.stream_bytes(f"/v1/files/{FILE_ID}/content")
        ]
        assert b"".join(chunks) == b"chunk-data"
    finally:
        await http.aclose()


# --- AsyncPager ------------------------------------------------------


async def test_pager_await_returns_first_page(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tasks",
        json_body=paginated([task_payload()], total_count=1),
    )
    pager = AsyncTasks(fake_api.async_client()).list(include_total=True)
    assert isinstance(pager, AsyncPager)
    page = await pager  # awaitable -> first page with envelope metadata
    assert page.total_count == 1
    assert str(page.records[0].id) == TASK_ID


async def test_pager_async_iter_walks_pages():
    id_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    id_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    pages = {
        None: paginated([task_payload(id=id_a)], next="cur"),
        "cur": paginated([task_payload(id=id_b)], next=None),
    }

    async def fetch(cursor):
        return pages[cursor]

    from introspection_sdk.pagination import async_cursor_paginate

    pager = async_cursor_paginate(fetch)
    ids = [t.id async for t in pager]
    assert [str(i) for i in ids] == [id_a, id_b]


async def test_parse_ag_ui_events_async():
    async def lines():
        for line in [
            "event: heartbeat",
            "data: {}",
            "",
            "event: ag_ui",
            (
                'data: {"type":"TEXT_MESSAGE_CONTENT",'
                '"messageId":"msg-1","delta":"hi"}'
            ),
            "",
        ]:
            yield line

    events = [e async for e in parse_ag_ui_events_async(lines())]
    assert [
        e.model_dump(exclude_none=True, by_alias=True)["delta"] for e in events
    ] == ["hi"]


# --- AsyncTasks ------------------------------------------------------


async def test_tasks_create_and_get(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    fake_api.add("GET", f"/v1/tasks/{TASK_ID}", json_body=task_payload())
    tasks = AsyncTasks(fake_api.async_client())
    res = await tasks.create(prompt="hello")
    assert str(res.task.id) == TASK_ID
    got = await tasks.get(TASK_ID)
    assert got.title == "Summarize repo"


async def test_tasks_start_returns_async_handle(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    handle = await AsyncTasks(fake_api.async_client()).start(prompt="go")
    assert isinstance(handle, AsyncRunHandle)
    assert handle.run.id == "run-1"


async def test_run_handle_stream_and_text(fake_api: FakeAPI):
    sse = (
        'event: ag_ui\ndata: {"type":"TEXT_MESSAGE_CONTENT",'
        '"messageId":"msg-1","delta":"hel"}\n\n'
        'event: ag_ui\ndata: {"type":"TEXT_MESSAGE_CHUNK",'
        '"messageId":"msg-1","delta":"lo"}\n\n'
    )
    fake_api.add(
        "POST", f"/v1/tasks/{TASK_ID}/runs", json_body=task_run_response()
    )
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}/runs/run-1/stream",
        content=sse.encode(),
    )
    handle = await AsyncTasks(fake_api.async_client()).runs.create(
        TASK_ID, message="x"
    )
    events = [e async for e in handle.stream()]
    assert [
        e.model_dump(exclude_none=True, by_alias=True)["delta"] for e in events
    ] == ["hel", "lo"]
    assert await handle.text() == "hello"


async def test_runs_create_with_kind_and_metadata(fake_api: FakeAPI):
    fake_api.add(
        "POST", f"/v1/tasks/{TASK_ID}/runs", json_body=task_run_response()
    )
    await AsyncTasks(fake_api.async_client()).runs.create(
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


async def test_runs_resume_posts_ag_ui_resume_entries(fake_api: FakeAPI):
    fake_api.add(
        "POST", f"/v1/tasks/{TASK_ID}/runs", json_body=task_run_response()
    )
    handle = await AsyncTasks(fake_api.async_client()).runs.resume(
        TASK_ID,
        resume=[
            ResumeEntry(interrupt_id="interrupt-1", status="resolved"),
            {"interruptId": "interrupt-2", "status": "cancelled"},
        ],
    )
    assert handle.run.id == "run-1"
    assert fake_api.last_request.json() == {
        "resume": [
            {"interruptId": "interrupt-1", "status": "resolved"},
            {"interruptId": "interrupt-2", "status": "cancelled"},
        ]
    }


async def test_run_handle_cancel(fake_api: FakeAPI):
    fake_api.add(
        "POST", f"/v1/tasks/{TASK_ID}/runs", json_body=task_run_response()
    )
    fake_api.add(
        "POST",
        f"/v1/tasks/{TASK_ID}/runs/run-1/cancel",
        json_body=task_cancel_response("run-1"),
    )
    handle = await AsyncTasks(fake_api.async_client()).runs.create(
        TASK_ID, message="x"
    )
    cancelled = await handle.cancel()
    assert cancelled.id == "run-1"


# --- AsyncFiles ------------------------------------------------------


async def test_files_create_text_and_download(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    fake_api.add("GET", f"/v1/files/{FILE_ID}/content", content=b"bytes-here")
    files = AsyncFiles(fake_api.async_client())
    created = await files.create_text(name="n.md", content="# hi")
    assert str(created.id) == FILE_ID
    data = await files.download(FILE_ID)
    assert data == b"bytes-here"


async def test_files_list_async_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    out = [f async for f in AsyncFiles(fake_api.async_client()).list()]
    assert len(out) == 1


# --- AsyncRunner ------------------------------------------------------


def _runner() -> AsyncRunner:
    spec = _spec()

    async def refresher() -> RunnerSpec:
        return spec

    return AsyncRunner(spec, refresher=refresher)


async def test_runner_accessors_and_namespaces():
    runner = _runner()
    assert runner.session_id == "sess-1"
    assert runner.dp_endpoint == "https://dp.test"
    assert isinstance(runner.tasks, AsyncTasks)
    assert isinstance(runner.files, AsyncFiles)
    await runner.close()


async def test_runner_refresh_swaps_spec():
    specs = iter([_spec(session_id="old"), _spec(session_id="new")])

    async def refresher() -> RunnerSpec:
        return next(specs)

    runner = AsyncRunner(next(specs), refresher=refresher)
    assert runner.session_id == "old"
    old_tasks = runner.tasks
    await runner.refresh()
    assert runner.session_id == "new"
    assert runner.tasks is not old_tasks
    await runner.close()


async def test_runner_close_blocks_use_and_aenter():
    async with _runner() as runner:
        assert runner.session_id == "sess-1"
    with pytest.raises(IntrospectionAPIError, match="has been closed"):
        _ = runner.tasks


# --- AsyncRuntimes / AsyncExperiments .run() -> AsyncRunner ----------


async def test_runtime_run_mints_async_runner(fake_api: FakeAPI):
    runtime_group_id = "33333333-3333-3333-3333-333333333333"
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )
    runtimes = AsyncRuntimes(fake_api.async_client())
    runner = await runtimes(runtime_group_id).run(identity={"user_id": "u1"})
    assert isinstance(runner, AsyncRunner)
    assert runner.dp_endpoint == "https://dp.test"
    assert fake_api.requests[0].params.get("runtime") == runtime_group_id
    await runner.close()


async def test_runtime_handle_resolves_slug(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )
    runtimes = AsyncRuntimes(fake_api.async_client())
    runner = await runtimes("checkout-agent").run()
    assert isinstance(runner, AsyncRunner)
    # First call lists by slug, second posts /run.
    assert fake_api.requests[0].path == "/v1/runtimes"
    assert fake_api.last_request.path == f"/v1/runtimes/{RUNTIME_ID}/run"
    await runner.close()


async def test_experiment_run_mints_async_runner(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/run",
        json_body=runner_spec_payload(),
    )
    experiments = AsyncExperiments(fake_api.async_client())
    runner = await experiments(UUID(EXPERIMENT_ID)).run()
    assert isinstance(runner, AsyncRunner)
    await runner.close()


async def test_experiment_lifecycle(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/start",
        json_body=experiment_payload(status="running"),
    )
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/end",
        json_body=experiment_payload(status="concluded"),
    )
    handle = AsyncExperiments(fake_api.async_client())(UUID(EXPERIMENT_ID))
    started = await handle.start()
    assert started.status == "running"
    ended = await handle.end(notes="done")
    assert ended.status == "concluded"
    assert fake_api.last_request.json()["notes"] == "done"


async def test_async_request_retries_on_429_then_succeeds(fake_api: FakeAPI):
    calls = {"n": 0}

    def handler(_request):
        import httpx

        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"detail": "rate limited"},
            )
        return httpx.Response(200, json={"ok": True})

    fake_api.add_handler("GET", "/v1/tasks/abc", handler)
    http = fake_api.async_client(retry_base=0.0)
    assert await http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 429 + successful retry


async def test_async_request_surfaces_rate_limit_after_exhausting(
    fake_api: FakeAPI,
):
    from introspection_sdk._errors import RateLimitError

    fake_api.add(
        "GET",
        "/v1/tasks/def",
        status=429,
        headers={"retry-after": "0"},
        json_body={"detail": "rate limited"},
    )
    http = fake_api.async_client(max_retries=1, retry_base=0.0)
    with pytest.raises(RateLimitError):
        await http.request("GET", "/v1/tasks/def")
    assert len(fake_api.requests) == 2  # initial + 1 retry


async def test_async_get_retries_on_503_without_retry_after(
    fake_api: FakeAPI,
):
    # No ``Retry-After`` header: the retry decision is status-based.
    calls = {"n": 0}

    def handler(_request):
        import httpx

        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"detail": "down"})
        return httpx.Response(200, json={"ok": True})

    fake_api.add_handler("GET", "/v1/tasks/abc", handler)
    http = fake_api.async_client(retry_base=0.0)
    assert await http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 503 + successful retry


async def test_async_get_retries_on_504(fake_api: FakeAPI):
    calls = {"n": 0}

    def handler(_request):
        import httpx

        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(504, json={"detail": "timeout"})
        return httpx.Response(200, json={"ok": True})

    fake_api.add_handler("GET", "/v1/tasks/abc", handler)
    http = fake_api.async_client(retry_base=0.0)
    assert await http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 504 + successful retry


async def test_async_post_503_surfaces_immediately(fake_api: FakeAPI):
    from introspection_sdk._errors import SandboxUnavailableError

    fake_api.add(
        "POST", "/v1/things", status=503, json_body={"detail": "down"}
    )
    http = fake_api.async_client(retry_base=0.0)
    with pytest.raises(SandboxUnavailableError):
        await http.request("POST", "/v1/things", json={"name": "widget"})
    assert len(fake_api.requests) == 1  # never retried
