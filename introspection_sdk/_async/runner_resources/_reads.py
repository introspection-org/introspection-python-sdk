"""Async twins re-exported by :mod:`introspection_sdk.runner_resources._reads`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

from introspection_sdk._http import RawResponse

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pyarrow as pa
from introspection_sdk.runner_resources._reads_common import (
    decode_arrow_table,
    import_pyarrow,
    next_cursor_header,
)


class AsyncArrowPageIterator:
    """Lazily iterate a list read as one ``pyarrow.Table`` per page.

    Yields each server page as a Table (constant memory — one page held
    at a time), driving the same opaque ``X-Next-Cursor`` token the JSON
    pager uses. Empty pages (no body) yield nothing. :meth:`read_all`
    concatenates every page into a single Table.
    """

    def __init__(
        self,
        fetch: Callable[[str | None], Awaitable[RawResponse]],
        *,
        start: str | None = None,
    ) -> None:
        self._fetch = fetch
        self._start = start

    async def __aiter__(self) -> AsyncIterator[pa.Table]:
        cursor = self._start
        while True:
            raw = await self._fetch(cursor)
            table = decode_arrow_table(raw)
            if table is not None:
                yield table
            cursor = next_cursor_header(raw)
            if cursor is None:
                return

    async def read_all(self) -> pa.Table:
        """Fetch every page and concatenate into one ``pyarrow.Table``."""
        pa = import_pyarrow()
        tables = [table async for table in self]
        if not tables:
            return pa.table({})
        return pa.concat_tables(tables)
