"""Contract tests for graceful stream resume (INT-252).

Drives the resumable turn consumer through the same in-process
``httpx.MockTransport`` route table as the other REST tests
(see ``conftest.FakeAPI``). The two HTTP surfaces resume composes — the
run ``/stream`` and the conversation ``/items`` transcript, plus the cheap
task status read — are scripted with real handlers; a severed stream is
modelled by a streaming response body that raises mid-iteration. Nothing in
``introspection_sdk`` is patched.

Covers the six acceptance scenarios from
``docs/design/sdk-resumable-streams.md`` §7, for both the sync and async
clients.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx

from introspection_sdk.resumable import (
    StreamEvent,
    TranscriptItem,
    TurnExhausted,
    TurnSettled,
    TurnWaiting,
)
from introspection_sdk.runner_resources.tasks import AsyncTasks, Tasks

from .conftest import TASK_ID, FakeAPI

RUN_ID = "run-1"
STREAM_PATH = f"/v1/tasks/{TASK_ID}/runs/{RUN_ID}/stream"
STATUS_PATH = f"/v1/tasks/{TASK_ID}"
ITEMS_PATH = f"/v1/conversations/{TASK_ID}/items"

_RUN_FINISHED = (
    'event: ag_ui\ndata: {"type":"RUN_FINISHED",'
    '"threadId":"t","runId":"run-1"}\n\n'
)
_RUN_STARTED = (
    'event: ag_ui\ndata: {"type":"RUN_STARTED",'
    '"threadId":"t","runId":"run-1"}\n\n'
)


# --- handler builders ------------------------------------------------


def _stream_handler(
    script: list[tuple[str, str]],
) -> Callable[[httpx.Request], httpx.Response]:
    """One entry per ``/stream`` attempt.

    Entry is ``(kind, payload)``: ``("clean", frames)`` /
    ``("severed", frames)`` / ``("429", phase)`` — the last models the DP
    readiness contract (not attachable yet) with ``Retry-After`` + a
    ``{status}`` body. The script clamps at its last entry so a long 429 run
    can be expressed with a single trailing ``"429"`` entry.
    """
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        kind, payload = script[idx]
        if kind == "clean":
            return httpx.Response(200, content=payload.encode())
        if kind == "429":
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"status": payload or "provisioning"},
            )

        def body() -> Iterator[bytes]:
            if payload:
                yield payload.encode()
            raise httpx.ReadError("connection reset")

        return httpx.Response(200, content=body())

    return handler


def _items_handler(
    landed: Callable[[], list[str]],
) -> Callable[[httpx.Request], httpx.Response]:
    """Serve the transcript items strictly after ``?after`` from ``landed()``."""

    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        ids = landed()
        if after is not None and after in ids:
            ids = ids[ids.index(after) + 1 :]
        data = [
            {
                "object": "conversation.item",
                "id": i,
                "type": "span",
                "trace_id": "t",
                "span_id": i,
                "created_at": "2025-01-01T00:00:00Z",
                "span_name": "x",
                "span_kind": "INTERNAL",
                "node_type": "span",
            }
            for i in ids
        ]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": data,
                "first_id": data[0]["id"] if data else None,
                "last_id": data[-1]["id"] if data else None,
                "has_more": False,
            },
        )

    return handler


def _status_response(status: str) -> dict[str, Any]:
    return {
        "id": TASK_ID,
        "org_id": "00000000-0000-0000-0000-0000000000aa",
        "project_id": "00000000-0000-0000-0000-0000000000bb",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "mode": "agent",
        "status": status,
        "is_archived": False,
    }


def _transcript_ids(events: list) -> list[str]:
    return [e.item.id for e in events if isinstance(e, TranscriptItem)]


def _waiting_statuses(events: list) -> list[str | None]:
    return [e.status for e in events if isinstance(e, TurnWaiting)]


def _opts() -> dict:
    # Tight grace window / poll so the ingest-lag loop stays fast in tests.
    return {"resume": True, "grace_window": 0.2, "poll": 0.001}


# --- sync ------------------------------------------------------------


def test_clean_completion_one_tail_zero_resumes(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("clean", _RUN_FINISHED)])
    )
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: ["a", "b"]))
    tasks = Tasks(fake_api.client())

    events = list(tasks.stream_turn(TASK_ID, RUN_ID, **_opts()))

    # Exactly one /stream attempt (zero resumes), no status read on clean close.
    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 1
    assert all(r.path != STATUS_PATH for r in fake_api.requests)
    assert _transcript_ids(events) == ["a", "b"]
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_mid_turn_drop_still_running(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler([("severed", _RUN_STARTED), ("clean", _RUN_FINISHED)]),
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("running"))
    fake_api.add_handler(
        "GET", ITEMS_PATH, _items_handler(lambda: ["a", "b", "c"])
    )
    tasks = Tasks(fake_api.client())

    events = list(tasks.stream_turn(TASK_ID, RUN_ID, **_opts()))

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 2
    assert sum(1 for r in fake_api.requests if r.path == STATUS_PATH) == 1
    # No missed items, no duplicates across the two catch-ups.
    assert _transcript_ids(events) == ["a", "b", "c"]
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_drop_at_completion_status_settled(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("severed", "")])
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("completed"))
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: ["a"]))
    tasks = Tasks(fake_api.client())

    events = list(tasks.stream_turn(TASK_ID, RUN_ID, **_opts()))

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 1
    assert _transcript_ids(events) == ["a"]
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_ingest_lag_grace_window(fake_api: FakeAPI):
    calls = {"n": 0}

    def landed() -> list[str]:
        calls["n"] += 1
        return ["late"] if calls["n"] >= 3 else []

    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("clean", _RUN_FINISHED)])
    )
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(landed))
    tasks = Tasks(fake_api.client())

    events = list(
        tasks.stream_turn(
            TASK_ID, RUN_ID, resume=True, grace_window=2.0, poll=0.001
        )
    )

    assert _transcript_ids(events) == ["late"]
    assert calls["n"] >= 3
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_exhausted_max_resumes(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler([("severed", "")] * 4),
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("running"))
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: []))
    tasks = Tasks(fake_api.client())

    events = list(
        tasks.stream_turn(
            TASK_ID,
            RUN_ID,
            resume=True,
            max_resumes=2,
            grace_window=0.05,
            poll=0.001,
        )
    )

    # max_resumes + 1 attempts, then stop — no infinite reconnect.
    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 3
    assert events[-1] == TurnExhausted()


def test_failed_mid_turn_settles_not_ok(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler([("severed", ""), ("severed", "")]),
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("failed"))
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: ["a"]))
    tasks = Tasks(fake_api.client())

    events = list(tasks.stream_turn(TASK_ID, RUN_ID, **_opts()))

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 1
    assert events[-1] == TurnSettled(ok=False, status="failed")


def test_resume_off_is_passthrough(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("clean", _RUN_FINISHED)])
    )
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: ["a"]))
    tasks = Tasks(fake_api.client())

    events = list(tasks.stream_turn(TASK_ID, RUN_ID, resume=False))

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 1
    # No transcript or status reads when opted out.
    assert all(
        r.path not in (ITEMS_PATH, STATUS_PATH) for r in fake_api.requests
    )
    assert _transcript_ids(events) == []
    assert isinstance(events[0], StreamEvent)
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_429_readiness_backs_off_then_attaches(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler(
            [
                ("429", "provisioning"),
                ("429", "starting"),
                ("clean", _RUN_FINISHED),
            ]
        ),
    )
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: ["a"]))
    tasks = Tasks(fake_api.client())

    events = list(
        tasks.stream_turn(
            TASK_ID,
            RUN_ID,
            resume=True,
            wait_for_start=False,  # opt into the 429 readiness contract
            retry_backoff=0.001,
            grace_window=0.05,
            poll=0.001,
            max_resumes=0,  # 429 retries must NOT consume the resume budget
        )
    )

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 3
    # 429 is readiness, never a settle check.
    assert all(r.path != STATUS_PATH for r in fake_api.requests)
    assert _waiting_statuses(events) == ["provisioning", "starting"]
    assert _transcript_ids(events) == ["a"]
    assert events[-1] == TurnSettled(ok=True, status="completed")


def test_429_forever_bounded_by_deadline(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("429", "provisioning")])
    )
    tasks = Tasks(fake_api.client())

    events = list(
        tasks.stream_turn(
            TASK_ID,
            RUN_ID,
            resume=True,
            wait_for_start=False,
            retry_backoff=0.001,
            timeout=0.05,  # overall deadline bounds the readiness wait
        )
    )

    assert events[-1] == TurnExhausted()
    assert len(_waiting_statuses(events)) > 0


# --- async -----------------------------------------------------------


async def _collect_async(agen) -> list:
    out = []
    async for ev in agen:
        out.append(ev)
    return out


async def test_async_mid_turn_drop_still_running(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler([("severed", _RUN_STARTED), ("clean", _RUN_FINISHED)]),
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("running"))
    fake_api.add_handler(
        "GET", ITEMS_PATH, _items_handler(lambda: ["a", "b", "c"])
    )
    tasks = AsyncTasks(fake_api.async_client())

    events = await _collect_async(
        tasks.stream_turn(TASK_ID, RUN_ID, **_opts())
    )

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 2
    assert _transcript_ids(events) == ["a", "b", "c"]
    assert events[-1] == TurnSettled(ok=True, status="completed")


async def test_async_exhausted_max_resumes(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("severed", "")] * 4)
    )
    fake_api.add("GET", STATUS_PATH, json_body=_status_response("running"))
    fake_api.add_handler("GET", ITEMS_PATH, _items_handler(lambda: []))
    tasks = AsyncTasks(fake_api.async_client())

    events = await _collect_async(
        tasks.stream_turn(
            TASK_ID,
            RUN_ID,
            resume=True,
            max_resumes=1,
            grace_window=0.05,
            poll=0.001,
        )
    )

    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 2
    assert events[-1] == TurnExhausted()
