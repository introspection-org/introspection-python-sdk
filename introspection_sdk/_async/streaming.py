"""Async twins re-exported by :mod:`introspection_sdk.streaming`."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator

from introspection_sdk._streaming_common import (
    _SseAccumulator,
    _SseEvent,
)
from introspection_sdk.schemas.agui import AGUIEvent, validate_ag_ui_event


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


async def parse_ag_ui_events_async(
    lines: AsyncIterable[str],
) -> AsyncIterator[AGUIEvent]:
    """Yield AG-UI events from ``event: ag_ui`` SSE frames.

    Non-AG-UI transport frames, such as heartbeats, are ignored.
    """
    async for event in _parse_sse_async(lines):
        if event.event != "ag_ui":
            continue
        payload = json.loads(event.data)
        yield validate_ag_ui_event(payload)
