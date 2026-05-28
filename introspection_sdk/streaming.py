"""Minimal Server-Sent Events parser over an iterator of lines.

DP returns ``text/event-stream`` and proxies raw frames from the
agents-worker; the DP does not define the event taxonomy. This parser
emits raw ``SseEvent`` dicts so callers can branch on ``event`` and
``json.loads`` ``data`` themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
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


def parse_sse(lines: Iterable[str]) -> Iterator[SseEvent]:
    """Yield ``SseEvent`` instances from a stream of SSE wire lines."""
    cur = SseEvent()
    has_content = False
    for line in lines:
        if line == "":
            if has_content:
                yield cur._finalize()
            cur = SseEvent()
            has_content = False
            continue
        if line.startswith(":"):
            continue
        field_name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field_name == "event":
            cur.event = value
            has_content = True
        elif field_name == "data":
            cur._data_parts.append(value)
            has_content = True
        elif field_name == "id":
            cur.id = value
            has_content = True
        elif field_name == "retry":
            try:
                cur.retry = int(value)
            except ValueError:
                pass
    if has_content:
        yield cur._finalize()
