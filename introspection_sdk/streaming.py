"""AG-UI event parsing over the task run SSE transport.

The HTTP response still uses Server-Sent Events as a transport detail, but
the public SDK surface yields validated AG-UI protocol events only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from introspection_sdk.schemas.agui import AGUIEvent, validate_ag_ui_event


@dataclass(slots=True)
class _SseEvent:
    event: str = "message"
    data: str = ""
    id: str | None = None
    retry: int | None = None
    _data_parts: list[str] = field(default_factory=list)

    def _finalize(self) -> _SseEvent:
        self.data = "\n".join(self._data_parts)
        return self


class _SseAccumulator:
    """Incremental SSE line parser shared by the sync and async drivers.

    Feed wire lines one at a time via :meth:`feed`; it returns a
    finalized SSE frame whenever a blank line closes a non-empty
    event, else ``None``. Call :meth:`flush` once the stream ends to emit
    any trailing event.
    """

    def __init__(self) -> None:
        self._cur = _SseEvent()
        self._has_content = False

    def feed(self, line: str) -> _SseEvent | None:
        if line == "":
            event = self._cur._finalize() if self._has_content else None
            self._cur = _SseEvent()
            self._has_content = False
            return event
        if line.startswith(":"):
            return None
        field_name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field_name == "event":
            self._cur.event = value
            self._has_content = True
        elif field_name == "data":
            self._cur._data_parts.append(value)
            self._has_content = True
        elif field_name == "id":
            self._cur.id = value
            self._has_content = True
        elif field_name == "retry":
            try:
                self._cur.retry = int(value)
            except ValueError:
                pass
        return None

    def flush(self) -> _SseEvent | None:
        return self._cur._finalize() if self._has_content else None


def _parse_sse(lines: Iterable[str]) -> Iterator[_SseEvent]:
    acc = _SseAccumulator()
    for line in lines:
        event = acc.feed(line)
        if event is not None:
            yield event
    tail = acc.flush()
    if tail is not None:
        yield tail


async def _parse_sse_async(
    lines: AsyncIterable[str],
) -> AsyncIterator[_SseEvent]:
    acc = _SseAccumulator()
    async for line in lines:
        event = acc.feed(line)
        if event is not None:
            yield event
    tail = acc.flush()
    if tail is not None:
        yield tail


def parse_ag_ui_events(lines: Iterable[str]) -> Iterator[AGUIEvent]:
    """Yield AG-UI events from ``event: ag_ui`` SSE frames.

    Non-AG-UI transport frames, such as heartbeats, are ignored.
    """
    for event in _parse_sse(lines):
        if event.event != "ag_ui":
            continue
        payload = json.loads(event.data)
        yield validate_ag_ui_event(payload)


async def parse_ag_ui_events_async(
    lines: AsyncIterable[str],
) -> AsyncIterator[AGUIEvent]:
    """Async twin of :func:`parse_ag_ui_events`."""
    async for event in _parse_sse_async(lines):
        if event.event != "ag_ui":
            continue
        payload: Any = json.loads(event.data)
        yield validate_ag_ui_event(payload)
