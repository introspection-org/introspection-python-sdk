"""Resume run streams using content cursors and the run-scoped status read.

This is the cross-SDK run-stream recovery contract, pinned by the shared
``run-stream-contract.json`` fixtures. Each SDK's test suite pins the
fixture's SHA-256, so a contract change updates all four copies (Swift,
JavaScript, Rust, Python) and their hashes together.

- **Cursor.** The first attach sends ``Last-Event-ID: 0``, so output
  produced before it is replayed. Every reconnect resumes from the last
  content cursor: the id of the last new content frame.
- **Completion.** Only a settling ``RUN_FINISHED`` or ``RUN_ERROR`` ends the
  sequence. A ``RUN_FINISHED`` whose ``result.reason`` is ``"stream_close"``
  only ends an attach, so it is not yielded.
- **Clean EOF.** When the stream closes without a settling event, the run's
  status is read (``GET /v1/tasks/{task_id}/runs/{run_id}``). ``failed`` or
  ``cancelled`` raises ``RunFailedError``; ``idle``, ``completed`` or
  ``awaiting_user`` raises ``StreamIncompleteError``, because the run
  settled without the stream confirming it. Anything else, including a
  status read that fails, reconnects.
- **Budget.** Reconnects are bounded by ``max_reconnects`` (default 5) and
  ``timeout`` (default 300 s), with backoff from ``backoff`` (default
  0.5 s). A new content cursor renews both, so a long run keeps a full
  recovery window; duplicate content, lifecycle events and heartbeats renew
  neither. The timeout is checked only before a reconnect, never while a
  connection is open. A ``429`` while the run is not attachable yet waits
  for ``Retry-After`` within the timeout and does not spend the reconnect
  budget.
- **Past the replay buffer.** When the cursor is older than what the
  runtime retains, the reconnect answers with one AG-UI
  ``MESSAGES_SNAPSHOT`` of the run's messages so far, and its id becomes the
  new cursor. When the runtime holds neither the frames nor a snapshot, it
  answers ``410`` and the stream raises ``StreamIncompleteError``. Runtime
  images older than the snapshot send a ``CUSTOM resume_gap`` event
  instead, which the stream yields.

Use a concrete run id for one turn. ``runs/current`` is a moving alias, so
a reconnect or status read can resolve to the next run.

The in-process fake sandbox (``mock://``) delivers replies only through the
conversation transcript. Its stream ends with an attach-level
``stream_close``, which ``text()`` cannot treat as a completed reply, so
test fake runs through transcript reads and ``text()`` against a real
runtime.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus

import httpx2 as httpx

from introspection_sdk._backoff import _retry_delay
from introspection_sdk._errors import (
    IntrospectionAPIError,
    NetworkError,
    RateLimitError,
    RunFailedError,
    StreamIncompleteError,
)
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.schemas.agui import (
    AGUIEvent,
    RunFinishedEvent,
    validate_ag_ui_event,
)
from introspection_sdk.schemas.tasks import TaskRun, TaskStatus
from introspection_sdk.streaming import _parse_sse, _parse_sse_async

# The delay math (capped-exponential with
# ``Retry-After`` as a floor) is shared with the unary clients via
# :mod:`introspection_sdk._backoff`; the reconnect *decisions* below are
# the stream's own.
_DEFAULT_MAX_RECONNECTS = 5
_DEFAULT_BACKOFF = 0.5
_DEFAULT_TIMEOUT = 300.0


def _is_severance(exc: BaseException) -> bool:
    """Whether ``exc`` is a dropped connection worth re-attaching for.

    A payload the SDK cannot parse or validate, and a terminal HTTP status,
    both fail again identically on reconnect.
    """
    return isinstance(exc, NetworkError | httpx.HTTPError)


def _run_path(task_id: str, run_id: str) -> str:
    return f"/v1/tasks/{task_id}/runs/{run_id}"


def _resume_headers(last_event_id: str | None) -> dict[str, str] | None:
    return {"Last-Event-ID": last_event_id} if last_event_id else None


def stream_resumable(
    http: _HttpClient,
    task_id: str,
    run_id: str,
    *,
    max_reconnects: int = _DEFAULT_MAX_RECONNECTS,
    backoff: float = _DEFAULT_BACKOFF,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Iterator[AGUIEvent]:
    """Consume a run's SSE stream as a resumable ``AGUIEvent`` sequence
    (sync), reconnecting transparently on a mid-turn disconnect via
    ``Last-Event-ID``. See the module docstring."""
    deadline = time.monotonic() + timeout
    # The last *content*-frame id, replayed via ``Last-Event-ID`` on reconnect.
    # Control frames (RUN_* lifecycle, heartbeats) carry a non-numeric ``c-…``
    # id that is not a valid resume cursor, so only numeric ids advance it.
    last_event_id = "0"
    reconnects = 0
    readiness_waits = 0

    while True:
        progressed = False
        lines = http.stream_sse_lines(
            _run_path(task_id, run_id) + "/stream",
            headers=_resume_headers(last_event_id),
        )
        try:
            for frame in _parse_sse(lines):
                if frame.event != "ag_ui":
                    continue  # ignore heartbeats etc.
                event = validate_ag_ui_event(json.loads(frame.data))
                control = event.type in {
                    "RUN_STARTED",
                    "RUN_FINISHED",
                    "RUN_ERROR",
                }
                if (
                    not control
                    and frame.id
                    and frame.id.isascii()
                    and frame.id.isdigit()
                ):
                    if int(frame.id) <= int(last_event_id):
                        continue
                    last_event_id = frame.id
                    deadline = time.monotonic() + timeout
                    progressed = True
                if (
                    isinstance(event, RunFinishedEvent)
                    and isinstance(event.result, dict)
                    and event.result.get("reason") == "stream_close"
                ):
                    continue
                yield event
                if event.type in {"RUN_FINISHED", "RUN_ERROR"}:
                    return
        except RateLimitError as exc:
            # Not attachable yet — a readiness wait, not a failed attempt.
            readiness_waits += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(
                min(
                    _retry_delay(readiness_waits, exc.retry_after, backoff),
                    remaining,
                )
            )
            continue
        except Exception as exc:
            if (
                isinstance(exc, IntrospectionAPIError)
                and exc.status_code == HTTPStatus.GONE
            ):
                raise StreamIncompleteError(
                    "The stream history is no longer available; read the conversation transcript"
                ) from exc
            if not _is_severance(exc):
                raise
            failure = exc
        else:
            state = None
            try:
                state = TaskRun.model_validate(
                    http.request(
                        "GET",
                        _run_path(task_id, run_id),
                    )
                )
            except (IntrospectionAPIError, httpx.HTTPError, ValueError):
                pass
            if state and state.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                raise RunFailedError(
                    f"The run ended with status {state.status}"
                )
            if state and state.status in {
                TaskStatus.IDLE,
                TaskStatus.COMPLETED,
                TaskStatus.AWAITING_USER,
            }:
                raise StreamIncompleteError(
                    "The run settled without a complete stream; read the conversation transcript"
                )
            failure = StreamIncompleteError(
                "The stream ended before the run settled"
            )
        reconnects = 0 if progressed else reconnects + 1
        remaining = deadline - time.monotonic()
        if reconnects > max_reconnects or remaining <= 0:
            raise failure
        time.sleep(min(_retry_delay(reconnects, None, backoff), remaining))


async def stream_resumable_async(
    http: _AsyncHttpClient,
    task_id: str,
    run_id: str,
    *,
    max_reconnects: int = _DEFAULT_MAX_RECONNECTS,
    backoff: float = _DEFAULT_BACKOFF,
    timeout: float = _DEFAULT_TIMEOUT,
) -> AsyncIterator[AGUIEvent]:
    """Async twin of :func:`stream_resumable`."""
    deadline = time.monotonic() + timeout
    last_event_id = "0"
    reconnects = 0
    readiness_waits = 0

    while True:
        progressed = False
        lines = http.stream_sse_lines(
            _run_path(task_id, run_id) + "/stream",
            headers=_resume_headers(last_event_id),
        )
        try:
            async for frame in _parse_sse_async(lines):
                if frame.event != "ag_ui":
                    continue
                event = validate_ag_ui_event(json.loads(frame.data))
                control = event.type in {
                    "RUN_STARTED",
                    "RUN_FINISHED",
                    "RUN_ERROR",
                }
                if (
                    not control
                    and frame.id
                    and frame.id.isascii()
                    and frame.id.isdigit()
                ):
                    if int(frame.id) <= int(last_event_id):
                        continue
                    last_event_id = frame.id
                    deadline = time.monotonic() + timeout
                    progressed = True
                if (
                    isinstance(event, RunFinishedEvent)
                    and isinstance(event.result, dict)
                    and event.result.get("reason") == "stream_close"
                ):
                    continue
                yield event
                if event.type in {"RUN_FINISHED", "RUN_ERROR"}:
                    return
        except RateLimitError as exc:
            readiness_waits += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            await asyncio.sleep(
                min(
                    _retry_delay(readiness_waits, exc.retry_after, backoff),
                    remaining,
                )
            )
            continue
        except Exception as exc:
            if (
                isinstance(exc, IntrospectionAPIError)
                and exc.status_code == HTTPStatus.GONE
            ):
                raise StreamIncompleteError(
                    "The stream history is no longer available; read the conversation transcript"
                ) from exc
            if not _is_severance(exc):
                raise
            failure = exc
        else:
            state = None
            try:
                state = TaskRun.model_validate(
                    await http.request(
                        "GET",
                        _run_path(task_id, run_id),
                    )
                )
            except (IntrospectionAPIError, httpx.HTTPError, ValueError):
                pass
            if state and state.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                raise RunFailedError(
                    f"The run ended with status {state.status}"
                )
            if state and state.status in {
                TaskStatus.IDLE,
                TaskStatus.COMPLETED,
                TaskStatus.AWAITING_USER,
            }:
                raise StreamIncompleteError(
                    "The run settled without a complete stream; read the conversation transcript"
                )
            failure = StreamIncompleteError(
                "The stream ended before the run settled"
            )
        reconnects = 0 if progressed else reconnects + 1
        remaining = deadline - time.monotonic()
        if reconnects > max_reconnects or remaining <= 0:
            raise failure
        await asyncio.sleep(
            min(_retry_delay(reconnects, None, backoff), remaining)
        )
