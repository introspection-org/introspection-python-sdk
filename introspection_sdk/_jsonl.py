"""JSON-lines response bodies, parsed as the bytes arrive."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any

__all__ = ["JSONL_ACCEPT_HEADERS", "iter_jsonl", "iter_jsonl_async"]

JSONL_ACCEPT_HEADERS = {"Accept": "application/x-ndjson"}


def _take_lines(buffer: bytes) -> tuple[list[bytes], bytes]:
    """The complete, non-blank lines of ``buffer`` and the partial tail."""
    *lines, rest = buffer.split(b"\n")
    return [line for line in lines if line.strip()], rest


def iter_jsonl(chunks: Iterable[bytes]) -> Iterator[Any]:
    """Yield one decoded JSON value per line; a line may span chunks."""
    buffer = b""
    for chunk in chunks:
        lines, buffer = _take_lines(buffer + chunk)
        for line in lines:
            yield json.loads(line)
    if buffer.strip():
        yield json.loads(buffer)


async def iter_jsonl_async(chunks: AsyncIterable[bytes]) -> AsyncIterator[Any]:
    """Async twin of :func:`iter_jsonl`."""
    buffer = b""
    async for chunk in chunks:
        lines, buffer = _take_lines(buffer + chunk)
        for line in lines:
            yield json.loads(line)
    if buffer.strip():
        yield json.loads(buffer)
