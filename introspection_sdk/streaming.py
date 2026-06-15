"""Minimal Server-Sent Events parser over an iterator of lines.

DP returns ``text/event-stream`` and proxies raw frames from the
agents-worker; the DP does not define the event taxonomy. This parser
emits raw ``SseEvent`` dicts so callers can branch on ``event`` and
``json.loads`` ``data`` themselves.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class SseEvent:
    event: str = "message"
    data: str = ""
    id: str | None = None
    retry: int | None = None
    _data_parts: list[str] = field(default_factory=list)

    def _finalize(self) -> SseEvent:
        self.data = "\n".join(self._data_parts)
        return self


class _SseAccumulator:
    """Incremental SSE line parser shared by the sync and async drivers.

    Feed wire lines one at a time via :meth:`feed`; it returns a
    finalized :class:`SseEvent` whenever a blank line closes a non-empty
    event, else ``None``. Call :meth:`flush` once the stream ends to emit
    any trailing event.
    """

    def __init__(self) -> None:
        self._cur = SseEvent()
        self._has_content = False

    def feed(self, line: str) -> SseEvent | None:
        if line == "":
            event = self._cur._finalize() if self._has_content else None
            self._cur = SseEvent()
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

    def flush(self) -> SseEvent | None:
        return self._cur._finalize() if self._has_content else None


def parse_sse(lines: Iterable[str]) -> Iterator[SseEvent]:
    """Yield ``SseEvent`` instances from a stream of SSE wire lines."""
    acc = _SseAccumulator()
    for line in lines:
        event = acc.feed(line)
        if event is not None:
            yield event
    tail = acc.flush()
    if tail is not None:
        yield tail


async def parse_sse_async(
    lines: AsyncIterable[str],
) -> AsyncIterator[SseEvent]:
    """Async twin of :func:`parse_sse` over an async stream of SSE wire
    lines."""
    acc = _SseAccumulator()
    async for line in lines:
        event = acc.feed(line)
        if event is not None:
            yield event
    tail = acc.flush()
    if tail is not None:
        yield tail
