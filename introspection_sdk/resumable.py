"""Graceful turn resume for the task run SSE stream (INT-252).

See ``docs/design/sdk-resumable-streams.md`` in ``introspection-cloud``.

A turn is consumed over a long-lived SSE stream that can be severed before
the turn settles (gateway idle-timeout, load-balancer recycle, network blip,
client sleep). The runtime does **no replay on reconnect, by design** —
recovery is transcript hydration. On a mid-turn disconnect this transparently
catches the missed output up from the durable transcript
(``GET /v1/conversations/{id}/items``) and re-attaches the live stream,
delivering a single gap-free, duplicate-free sequence to the caller — bounded
by ``max_resumes`` and an overall deadline so it never reconnects forever.

Readiness has two modes (design §6 phased migration). By default the attach
sends ``wait_for_start=1`` (the DP long-polls the connection open until the run
is live) — the current transition default. Passing ``wait_for_start=False``
sends ``wait_for_start=0`` and opts into the target ``429``-retry contract: the
DP returns ``429`` + ``Retry-After`` + ``{status}`` while the run is not yet
attachable and ``200`` + SSE once it is. Either way, when a ``429`` is seen this
honours ``Retry-After`` as the floor of a capped-exponential backoff and retries
the attach — surfacing each wait as a :class:`TurnWaiting` event — without
consuming a resume.

Resume is a **pure client** concern: no server-side replay buffer, no new API
surface. Dedup is by the transcript item's stable ``id`` only (never by the
live frame's ephemeral, connection-local id).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

from introspection_sdk._errors import RateLimitError
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.runner_resources.conversations import (
    AsyncConversationItems,
    ConversationItems,
)
from introspection_sdk.schemas.agui import AGUIEvent, EventType
from introspection_sdk.schemas.conversations import ConversationItem
from introspection_sdk.schemas.tasks import Task, TaskStatus
from introspection_sdk.streaming import (
    parse_ag_ui_events,
    parse_ag_ui_events_async,
)

# Statuses that mean *this turn* settled. ``idle`` = the turn settled but the
# task is still alive (multi-turn); for a single turn's resume loop that is
# settled-success.
_SETTLED_OK: frozenset[TaskStatus] = frozenset(
    {TaskStatus.IDLE, TaskStatus.COMPLETED}
)
_SETTLED_FAILED: frozenset[TaskStatus] = frozenset(
    {TaskStatus.FAILED, TaskStatus.CANCELLED}
)

# Defaults match the reference implementation and the other SDKs.
_DEFAULT_MAX_RESUMES = 3
_DEFAULT_GRACE_WINDOW = 5.0
_DEFAULT_POLL = 0.5
_DEFAULT_RETRY_BACKOFF = 0.5
_MAX_RETRY_BACKOFF = 10.0
_DEFAULT_PAGE_LIMIT = 200
_DEFAULT_TIMEOUT = 300.0


@dataclass(slots=True)
class StreamEvent:
    """A live AG-UI event delivered from the attached ``/stream``."""

    event: AGUIEvent


@dataclass(slots=True)
class TranscriptItem:
    """A durable transcript item delivered during gap catch-up.

    Live events and transcript items are distinct representations — the live
    frame id is ephemeral and does not correlate to a transcript id — so dedup
    applies to transcript items only (by stable ``id``, across catch-ups).
    """

    item: ConversationItem


@dataclass(slots=True)
class TurnWaiting:
    """Readiness notice: the DP is not attachable yet (``429``).

    ``status`` is the phase from the ``429`` body when present; ``retry_after``
    is the ``Retry-After`` hint in seconds. The consumer backs off and retries
    the attach — this does not consume a resume.
    """

    status: str | None
    retry_after: float | None


@dataclass(slots=True)
class TurnSettled:
    """Terminal marker: the turn finished. ``ok`` is success vs failure."""

    ok: bool
    status: str


@dataclass(slots=True)
class TurnExhausted:
    """Terminal marker: ``max_resumes`` / deadline hit before the turn settled.

    Surfaced rather than looping forever — the caller decides whether to retry.
    """


ResumableTurnEvent = (
    StreamEvent | TranscriptItem | TurnWaiting | TurnSettled | TurnExhausted
)


@dataclass(slots=True)
class _StreamOutcome:
    closed_cleanly: bool = False
    saw_run_error: bool = False
    rate_limited: bool = False
    retry_after: float | None = None
    phase: str | None = None


@dataclass(slots=True)
class _GapState:
    bookmark: str | None
    seen: set[str]


def _stream_path(task_id: str, run_id: str) -> str:
    return f"/v1/tasks/{task_id}/runs/{run_id}/stream"


def _wait_for_start_params(wait_for_start: bool) -> dict[str, int]:
    # Default ``wait_for_start=1`` (DP long-poll) during the migration; opt into
    # the 429 readiness contract with ``wait_for_start=False`` (design §6).
    return {"wait_for_start": 1 if wait_for_start else 0}


def _phase(body: Any) -> str | None:
    """The DP's readiness phase, if the ``429`` body carries a ``status``."""
    if isinstance(body, dict):
        status = body.get("status")
        if isinstance(status, str):
            return status
    return None


def _retry_backoff(n: int, retry_after: float | None, base: float) -> float:
    """``Retry-After`` as the floor of a capped-exponential step."""
    exp = min(base * (2**n), _MAX_RETRY_BACKOFF)
    return max(retry_after or 0.0, exp)


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


def _consume_stream(
    http: _HttpClient,
    task_id: str,
    run_id: str,
    outcome: _StreamOutcome,
    *,
    wait_for_start: bool,
) -> Iterator[AGUIEvent]:
    """Consume one ``/stream`` attachment to EOF, yielding AG-UI events.

    Records into ``outcome`` whether the stream closed cleanly (turn
    complete), was severed (an exception mid-read), or was refused with a
    ``429`` readiness signal (the run is not attachable yet).
    """
    try:
        lines = http.stream_sse_lines(
            _stream_path(task_id, run_id),
            params=_wait_for_start_params(wait_for_start),
        )
        for event in parse_ag_ui_events(lines):
            if event.type == EventType.RUN_ERROR:
                outcome.saw_run_error = True
            yield event
        # Reader reached EOF without raising: the DP closed the stream on turn
        # completion. A clean close with no error frame = the turn completed.
        outcome.closed_cleanly = True
    except RateLimitError as exc:
        # Not attachable yet — back off and retry the attach (design §6).
        outcome.rate_limited = True
        outcome.retry_after = exc.retry_after
        outcome.phase = _phase(exc.body)
    except Exception:
        # Severed before completion (network blip, idle-timeout).
        outcome.closed_cleanly = False


def _task_status(http: _HttpClient, task_id: str) -> TaskStatus | None:
    """Cheap status read — ``GET /v1/tasks/{id}``, never ``?include=agent``."""
    try:
        payload = http.request("GET", f"/v1/tasks/{task_id}")
        return Task.model_validate(payload).status
    except Exception:
        return None


def _hydrate_gap(
    items: ConversationItems,
    conversation_id: str,
    state: _GapState,
    *,
    grace_window: float,
    poll: float,
    page_limit: int,
) -> Iterator[ConversationItem]:
    """Durable catch-up across the telemetry ingest grace window.

    Pages the transcript forward from ``state.bookmark``
    (``order=asc&after=``), yielding each not-yet-seen item, then waits out
    late-landing items until a full grace window passes with nothing new.
    ``state`` is mutated so the dedup set + bookmark carry across successive
    catch-ups within one turn.
    """
    deadline = time.monotonic() + grace_window
    while True:
        gained = 0
        # ``ConversationItems.list`` auto-pages every ``has_more`` page.
        for item in items.list(
            conversation_id,
            order="asc",
            limit=page_limit,
            after=state.bookmark,
        ):
            if item.id in state.seen:
                continue
            state.seen.add(item.id)
            state.bookmark = item.id
            gained += 1
            yield item
        if gained == 0 and time.monotonic() >= deadline:
            break
        if gained == 0:
            time.sleep(poll)  # wait out the ingest grace window
        elif time.monotonic() >= deadline:
            break


def stream_turn_resumable(
    http: _HttpClient,
    task_id: str,
    run_id: str,
    *,
    resume: bool = False,
    wait_for_start: bool = True,
    conversation_id: str | None = None,
    max_resumes: int = _DEFAULT_MAX_RESUMES,
    grace_window: float = _DEFAULT_GRACE_WINDOW,
    poll: float = _DEFAULT_POLL,
    retry_backoff: float = _DEFAULT_RETRY_BACKOFF,
    page_limit: int = _DEFAULT_PAGE_LIMIT,
    after_id: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Iterator[ResumableTurnEvent]:
    """Consume a run as a resilient turn (sync). See the module docstring.

    Yields :class:`StreamEvent` (live), :class:`TranscriptItem` (catch-up) and
    :class:`TurnWaiting` (``429`` readiness) as a single sequence, ending with
    a terminal :class:`TurnSettled` or :class:`TurnExhausted`. ``resume`` is
    opt-in (default off); when false the turn is streamed once with no
    transcript catch-up or reconnect after a drop, but the readiness ``429``
    wait still applies.
    """
    conv_id = conversation_id or task_id
    items = ConversationItems(http)
    state = _GapState(bookmark=after_id, seen=set())
    start = time.monotonic()
    attempts = 0
    retry_429 = 0

    while time.monotonic() - start < timeout:
        outcome = _StreamOutcome()
        for event in _consume_stream(
            http, task_id, run_id, outcome, wait_for_start=wait_for_start
        ):
            yield StreamEvent(event)

        if outcome.rate_limited:
            yield TurnWaiting(outcome.phase, outcome.retry_after)
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            wait = _retry_backoff(
                retry_429, outcome.retry_after, retry_backoff
            )
            retry_429 += 1
            time.sleep(min(wait, remaining))
            continue  # retry the attach — readiness wait, not a resume
        retry_429 = 0
        attempts += 1

        # Resume opt-out: stream once, no catch-up, no reconnect.
        if not resume:
            yield TurnSettled(
                ok=outcome.closed_cleanly and not outcome.saw_run_error,
                status="completed",
            )
            return

        if outcome.closed_cleanly:
            # Clean close = turn complete; one final catch-up closes the
            # ingest-lag tail.
            for item in _hydrate_gap(
                items,
                conv_id,
                state,
                grace_window=grace_window,
                poll=poll,
                page_limit=page_limit,
            ):
                yield TranscriptItem(item)
            yield TurnSettled(ok=not outcome.saw_run_error, status="completed")
            return

        # Stream severed before completion — did the turn actually finish? The
        # cheap status read decides; catch up the durable gap either way.
        status = _task_status(http, task_id)
        for item in _hydrate_gap(
            items,
            conv_id,
            state,
            grace_window=grace_window,
            poll=poll,
            page_limit=page_limit,
        ):
            yield TranscriptItem(item)

        if status in _SETTLED_OK:
            yield TurnSettled(ok=True, status=str(status.value))
            return
        if status in _SETTLED_FAILED:
            yield TurnSettled(ok=False, status=str(status.value))
            return
        # pending|queued|scheduled|running|awaiting_user|cancelling → still
        # live; re-open /stream for the rest of the turn, bounded by
        # ``max_resumes``.
        if attempts > max_resumes:
            break

    # Exhausted max_resumes / deadline — surface it, do not loop forever.
    yield TurnExhausted()


# --------------------------------------------------------------------------
# Async
# --------------------------------------------------------------------------


async def _consume_stream_async(
    http: _AsyncHttpClient,
    task_id: str,
    run_id: str,
    outcome: _StreamOutcome,
    *,
    wait_for_start: bool,
) -> AsyncIterator[AGUIEvent]:
    try:
        lines = http.stream_sse_lines(
            _stream_path(task_id, run_id),
            params=_wait_for_start_params(wait_for_start),
        )
        async for event in parse_ag_ui_events_async(lines):
            if event.type == EventType.RUN_ERROR:
                outcome.saw_run_error = True
            yield event
        outcome.closed_cleanly = True
    except RateLimitError as exc:
        outcome.rate_limited = True
        outcome.retry_after = exc.retry_after
        outcome.phase = _phase(exc.body)
    except Exception:
        outcome.closed_cleanly = False


async def _task_status_async(
    http: _AsyncHttpClient, task_id: str
) -> TaskStatus | None:
    try:
        payload = await http.request("GET", f"/v1/tasks/{task_id}")
        return Task.model_validate(payload).status
    except Exception:
        return None


async def _hydrate_gap_async(
    items: AsyncConversationItems,
    conversation_id: str,
    state: _GapState,
    *,
    grace_window: float,
    poll: float,
    page_limit: int,
) -> AsyncIterator[ConversationItem]:
    deadline = time.monotonic() + grace_window
    while True:
        gained = 0
        async for item in items.list(
            conversation_id,
            order="asc",
            limit=page_limit,
            after=state.bookmark,
        ):
            if item.id in state.seen:
                continue
            state.seen.add(item.id)
            state.bookmark = item.id
            gained += 1
            yield item
        if gained == 0 and time.monotonic() >= deadline:
            break
        if gained == 0:
            await asyncio.sleep(poll)
        elif time.monotonic() >= deadline:
            break


async def stream_turn_resumable_async(
    http: _AsyncHttpClient,
    task_id: str,
    run_id: str,
    *,
    resume: bool = False,
    wait_for_start: bool = True,
    conversation_id: str | None = None,
    max_resumes: int = _DEFAULT_MAX_RESUMES,
    grace_window: float = _DEFAULT_GRACE_WINDOW,
    poll: float = _DEFAULT_POLL,
    retry_backoff: float = _DEFAULT_RETRY_BACKOFF,
    page_limit: int = _DEFAULT_PAGE_LIMIT,
    after_id: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> AsyncIterator[ResumableTurnEvent]:
    """Async twin of :func:`stream_turn_resumable`."""
    conv_id = conversation_id or task_id
    items = AsyncConversationItems(http)
    state = _GapState(bookmark=after_id, seen=set())
    start = time.monotonic()
    attempts = 0
    retry_429 = 0

    while time.monotonic() - start < timeout:
        outcome = _StreamOutcome()
        async for event in _consume_stream_async(
            http, task_id, run_id, outcome, wait_for_start=wait_for_start
        ):
            yield StreamEvent(event)

        if outcome.rate_limited:
            yield TurnWaiting(outcome.phase, outcome.retry_after)
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            wait = _retry_backoff(
                retry_429, outcome.retry_after, retry_backoff
            )
            retry_429 += 1
            await asyncio.sleep(min(wait, remaining))
            continue
        retry_429 = 0
        attempts += 1

        if not resume:
            yield TurnSettled(
                ok=outcome.closed_cleanly and not outcome.saw_run_error,
                status="completed",
            )
            return

        if outcome.closed_cleanly:
            async for item in _hydrate_gap_async(
                items,
                conv_id,
                state,
                grace_window=grace_window,
                poll=poll,
                page_limit=page_limit,
            ):
                yield TranscriptItem(item)
            yield TurnSettled(ok=not outcome.saw_run_error, status="completed")
            return

        status = await _task_status_async(http, task_id)
        async for item in _hydrate_gap_async(
            items,
            conv_id,
            state,
            grace_window=grace_window,
            poll=poll,
            page_limit=page_limit,
        ):
            yield TranscriptItem(item)

        if status in _SETTLED_OK:
            yield TurnSettled(ok=True, status=str(status.value))
            return
        if status in _SETTLED_FAILED:
            yield TurnSettled(ok=False, status=str(status.value))
            return
        if attempts > max_resumes:
            break

    yield TurnExhausted()
