"""Code shared by the sync and async twins in :mod:`introspection_sdk.streaming`."""

from __future__ import annotations

from dataclasses import dataclass, field


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
