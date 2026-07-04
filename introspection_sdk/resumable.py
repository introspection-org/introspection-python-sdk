"""Transparent stream resume for the task run SSE stream (INT-252).

See ``docs/design/sdk-resumable-streams.md`` in ``introspection-cloud``.

A turn is consumed over a long-lived SSE stream that can be severed before the
turn settles (gateway idle-timeout, load-balancer recycle, network blip). Rather
than surface that as a turn failure — losing every event between the drop and a
manual retry — the run stream reconnects **transparently**: it tracks the last
content-frame id and re-attaches with the SSE-standard ``Last-Event-ID`` header,
so the server replays the frames the client missed and the iterator yields a
single gap-free ``AGUIEvent`` sequence. There is **no consumer-visible change**:
the stream either completes (the DP closed it on turn completion) or raises once
recovery is exhausted, exactly like a plain stream.

Readiness folds in the same way: a not-yet-attachable run answers the attach
with ``429`` + ``Retry-After``, which is honoured as a backoff floor and retried
— never surfaced to the caller.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator

from introspection_sdk._backoff import _retry_delay
from introspection_sdk._errors import RateLimitError
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.schemas.agui import AGUIEvent, validate_ag_ui_event
from introspection_sdk.streaming import _parse_sse, _parse_sse_async

# Defaults match the other SDKs. The delay math (capped-exponential with
# ``Retry-After`` as a floor) is shared with the unary clients via
# :mod:`introspection_sdk._backoff`; the reconnect *decisions* below are
# the stream's own.
_DEFAULT_MAX_RECONNECTS = 5
_DEFAULT_BACKOFF = 0.5
_DEFAULT_TIMEOUT = 300.0


def _stream_path(task_id: str, run_id: str) -> str:
    return f"/v1/tasks/{task_id}/runs/{run_id}/stream"


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
    """Consume a run's SSE stream as a single gap-free ``AGUIEvent`` sequence
    (sync), reconnecting transparently on a mid-turn disconnect via
    ``Last-Event-ID``. See the module docstring."""
    deadline = time.monotonic() + timeout
    # The last *content*-frame id, replayed via ``Last-Event-ID`` on reconnect.
    # Control frames (RUN_* lifecycle, heartbeats) carry a non-numeric ``c-…``
    # id that is not a valid resume cursor, so only numeric ids advance it.
    last_event_id: str | None = None
    reconnects = 0

    while True:
        progressed = False
        lines = http.stream_sse_lines(
            _stream_path(task_id, run_id),
            headers=_resume_headers(last_event_id),
        )
        try:
            for frame in _parse_sse(lines):
                if frame.id and frame.id.isdigit():
                    last_event_id = frame.id
                if frame.event != "ag_ui":
                    continue  # ignore heartbeats etc.
                progressed = True
                yield validate_ag_ui_event(json.loads(frame.data))
            return  # clean EOF: the DP closed the stream on turn completion
        except RateLimitError as exc:
            # Not attachable yet — a readiness wait, not a failed attempt.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(
                min(
                    _retry_delay(reconnects, exc.retry_after, backoff),
                    remaining,
                )
            )
        except Exception:
            # Severed mid-read. Forward progress resets the budget; a reconnect
            # that delivers nothing counts down.
            reconnects = 0 if progressed else reconnects + 1
            remaining = deadline - time.monotonic()
            if reconnects > max_reconnects or remaining <= 0:
                raise
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
    last_event_id: str | None = None
    reconnects = 0

    while True:
        progressed = False
        lines = http.stream_sse_lines(
            _stream_path(task_id, run_id),
            headers=_resume_headers(last_event_id),
        )
        try:
            async for frame in _parse_sse_async(lines):
                if frame.id and frame.id.isdigit():
                    last_event_id = frame.id
                if frame.event != "ag_ui":
                    continue
                progressed = True
                yield validate_ag_ui_event(json.loads(frame.data))
            return
        except RateLimitError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            await asyncio.sleep(
                min(
                    _retry_delay(reconnects, exc.retry_after, backoff),
                    remaining,
                )
            )
        except Exception:
            reconnects = 0 if progressed else reconnects + 1
            remaining = deadline - time.monotonic()
            if reconnects > max_reconnects or remaining <= 0:
                raise
            await asyncio.sleep(
                min(_retry_delay(reconnects, None, backoff), remaining)
            )
