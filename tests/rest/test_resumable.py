"""Contract tests for transparent stream resume (INT-252).

Drives the run stream through the same in-process ``httpx.MockTransport``
route table as the other REST tests (see ``conftest.FakeAPI``). A severed
stream is modelled by a streaming response body that raises mid-iteration; a
not-yet-attachable run by a ``429`` + ``Retry-After``. The stream reconnects
transparently with ``Last-Event-ID`` and yields one gap-free ``AGUIEvent``
sequence — nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from introspection_sdk._errors import IntrospectionAPIError
from introspection_sdk.runner_resources.tasks import AsyncTasks, Tasks

from .conftest import TASK_ID, FakeAPI

RUN_ID = "run-1"
STREAM_PATH = f"/v1/tasks/{TASK_ID}/runs/{RUN_ID}/stream"


class _SeveredStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A response body that yields `body` then errors — modelling a connection
    severed mid-turn. Implements both the sync and async byte-stream protocols
    so the one ``MockTransport`` route backs both clients."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __iter__(self) -> Iterator[bytes]:
        if self._body:
            yield self._body
        raise httpx.ReadError("connection reset")

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self._body:
            yield self._body
        raise httpx.ReadError("connection reset")


def _content(seq: str, delta: str) -> str:
    return (
        f"id: {seq}\nevent: ag_ui\n"
        f'data: {{"type":"TEXT_MESSAGE_CONTENT","messageId":"m","delta":"{delta}"}}\n\n'
    )


_FINISH = (
    'id: c-0\nevent: ag_ui\ndata: {"type":"RUN_FINISHED",'
    '"threadId":"t","runId":"run-1"}\n\n'
)


class _StreamHandler:
    """A scripted ``/stream`` responder. One entry per attach: ``("clean",
    body)`` ends cleanly; ``("severed", body)`` raises mid-read; ``("429", "")``
    refuses with Retry-After. Records the ``Last-Event-ID`` header per call in
    ``seen``."""

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self._script = script
        self._n = 0
        self.seen: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request.headers.get("last-event-id"))
        kind, body = self._script[min(self._n, len(self._script) - 1)]
        self._n += 1
        if kind == "clean":
            return httpx.Response(200, content=body.encode())
        if kind == "429":
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"status": "provisioning"},
            )
        return httpx.Response(200, stream=_SeveredStream(body.encode()))


def _stream_handler(script: list[tuple[str, str]]) -> _StreamHandler:
    return _StreamHandler(script)


def _deltas(events: list) -> list[str]:
    return [
        e.delta
        for e in events
        if getattr(e, "type", None) == "TEXT_MESSAGE_CONTENT"
    ]


# --- sync ------------------------------------------------------------


def test_clean_completion_single_attach(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler(
            [("clean", _content("1", "a") + _content("2", "b") + _FINISH)]
        ),
    )
    tasks = Tasks(fake_api.client())

    events = list(tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001))

    assert _deltas(events) == ["a", "b"]
    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 1


def test_mid_turn_drop_reattaches_with_last_event_id(fake_api: FakeAPI):
    handler = _stream_handler(
        [
            ("severed", _content("1", "a") + _content("2", "b")),
            ("clean", _content("3", "c") + _FINISH),
        ]
    )
    fake_api.add_handler("GET", STREAM_PATH, handler)
    tasks = Tasks(fake_api.client())

    events = list(tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001))

    assert _deltas(events) == ["a", "b", "c"]  # gap-free
    # Reconnect resumes from the last numeric content-frame id seen.
    assert handler.seen == [None, "2"]


def test_resume_cursor_ignores_control_ids(fake_api: FakeAPI):
    heartbeat = 'id: c-9\nevent: heartbeat\ndata: {"runId":"run-1"}\n\n'
    handler = _stream_handler(
        [
            ("severed", _content("5", "a") + heartbeat),
            ("clean", _content("6", "b") + _FINISH),
        ]
    )
    fake_api.add_handler("GET", STREAM_PATH, handler)
    tasks = Tasks(fake_api.client())

    events = list(tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001))

    assert _deltas(events) == ["a", "b"]
    assert handler.seen == [None, "5"]  # "c-9" is not a cursor


def test_429_readiness_backs_off_then_attaches(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler(
            [("429", ""), ("429", ""), ("clean", _content("1", "a") + _FINISH)]
        ),
    )
    tasks = Tasks(fake_api.client())

    events = list(tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001))

    assert _deltas(events) == ["a"]  # 429 never surfaced
    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 3


def test_exhausts_reconnects_raises(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", STREAM_PATH, _stream_handler([("severed", "")])
    )
    tasks = Tasks(fake_api.client())

    with pytest.raises(IntrospectionAPIError):
        list(
            tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001, max_reconnects=2)
        )
    assert sum(1 for r in fake_api.requests if r.path == STREAM_PATH) == 3


def test_forward_progress_resets_budget(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        STREAM_PATH,
        _stream_handler(
            [
                ("severed", _content("1", "a")),
                ("severed", _content("2", "b")),
                ("severed", _content("3", "c")),
                ("clean", _content("4", "d") + _FINISH),
            ]
        ),
    )
    tasks = Tasks(fake_api.client())

    events = list(
        tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001, max_reconnects=1)
    )

    assert _deltas(events) == ["a", "b", "c", "d"]


# --- async -----------------------------------------------------------


async def _collect_async(agen) -> list:
    return [ev async for ev in agen]


async def test_async_mid_turn_drop_reattaches(fake_api: FakeAPI):
    handler = _stream_handler(
        [
            ("severed", _content("1", "a") + _content("2", "b")),
            ("clean", _content("3", "c") + _FINISH),
        ]
    )
    fake_api.add_handler("GET", STREAM_PATH, handler)
    tasks = AsyncTasks(fake_api.async_client())

    events = await _collect_async(
        tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001)
    )

    assert _deltas(events) == ["a", "b", "c"]
    assert handler.seen == [None, "2"]
