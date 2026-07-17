"""Shared helpers for the runner-scoped DP telemetry list reads.

Two concerns live here, common to ``runner.conversations`` and
``runner.events``:

* **Ergonomic window params.** The DP list routes take ``start_date`` /
  ``end_date`` (ISO datetimes) and ``direction`` (``asc``/``desc``). The
  SDK also accepts the friendlier ``start`` / ``end`` / ``order`` aliases
  plus a relative ``lookback`` (e.g. ``"24h"``) that resolves to
  ``start_date = now - lookback``. ``lookback`` is mutually exclusive with
  ``start`` / ``end`` — passing both raises ``ValueError`` locally, before
  any request is sent.
* **Optional Arrow decode.** With ``format="arrow"`` the list read sends
  ``Accept: application/vnd.apache.arrow.stream`` and the server returns an
  Arrow IPC *stream* (envelope columns plus a typed ``payload`` struct
  column) with the pagination metadata on response headers.
  :func:`decode_arrow_page` rebuilds the identical
  :class:`~introspection_sdk.schemas.pagination.Paginated` envelope the JSON
  path produces, so the auto-paging ``Pager`` drives both formats
  unchanged.
* **Columnar page iteration.** The ``.arrow()`` accessors return an
  :class:`ArrowPageIterator` / :class:`AsyncArrowPageIterator` yielding one
  ``pyarrow.Table`` per server page (constant memory), with a
  ``read_all()`` convenience concatenating every page into one Table.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import BaseModel

from introspection_sdk._http import RawResponse
from introspection_sdk.schemas.pagination import Paginated

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pyarrow as pa

T = TypeVar("T", bound=BaseModel)

#: Response representation for a list read: the default JSON envelope or the
#: columnar Arrow IPC stream.
ReadFormat = Literal["json", "arrow"]

#: Media type of the Arrow IPC *streaming* format (schema message + record
#: batches + EOS) — matches the DP ``serialization.ARROW_STREAM_MEDIA_TYPE``.
ARROW_STREAM_MEDIA_TYPE = "application/vnd.apache.arrow.stream"

#: Accept header injected on the Arrow path.
ARROW_ACCEPT_HEADERS: dict[str, str] = {"Accept": ARROW_STREAM_MEDIA_TYPE}

LOOKBACK_UNITS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}
LOOKBACK_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$")


def parse_lookback(lookback: str) -> timedelta:
    """Parse a relative window like ``"24h"`` / ``"7d"`` into a timedelta.

    Accepts a positive integer followed by one of ``s`` (seconds), ``m``
    (minutes), ``h`` (hours), ``d`` (days), or ``w`` (weeks). Raises
    ``ValueError`` on anything else.
    """
    match = LOOKBACK_RE.match(lookback)
    if match is None:
        raise ValueError(
            f"invalid lookback {lookback!r}; expected e.g. '24h', '7d', '30m'"
        )
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"lookback must be positive, got {lookback!r}")
    return timedelta(seconds=amount * LOOKBACK_UNITS[match.group(2)])


def resolve_window(
    *,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    lookback: str | None = None,
    start_date: str | datetime | None = None,
    end_date: str | datetime | None = None,
) -> tuple[str | datetime | None, str | datetime | None]:
    """Fold the ergonomic window aliases into ``(start_date, end_date)``.

    ``start`` / ``end`` are aliases for the explicit ``start_date`` /
    ``end_date``; ``lookback`` computes ``start_date = now - lookback``.
    ``lookback`` is mutually exclusive with ``start`` / ``end`` /
    ``start_date`` / ``end_date`` — passing both raises ``ValueError``
    before any request goes out.
    """
    resolved_start = start if start is not None else start_date
    resolved_end = end if end is not None else end_date
    if lookback is not None:
        if resolved_start is not None or resolved_end is not None:
            raise ValueError(
                "lookback is mutually exclusive with start/end "
                "(start_date/end_date)"
            )
        return datetime.now(UTC) - parse_lookback(lookback), None
    return resolved_start, resolved_end


def import_pyarrow() -> ModuleType:
    """Import ``pyarrow`` lazily, steering the caller at the ``[arrow]``
    extra when it is not installed."""
    try:
        import pyarrow as pa
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "format='arrow' requires the 'pyarrow' package. Install it with "
            "`pip install pyarrow` (or `pip install introspection-sdk[arrow]`)."
        ) from exc
    return pa


def next_cursor_header(raw: RawResponse) -> str | None:
    """Read the opaque next-page token off an Arrow list response."""
    headers = raw.headers
    return headers.get("X-Next-Cursor") or headers.get("x-next-cursor") or None


def decode_arrow_table(raw: RawResponse) -> pa.Table | None:
    """Decode an Arrow IPC stream body into one ``pyarrow.Table``.

    Returns ``None`` for an empty body (an empty page carries no schema
    message at all)."""
    pa = import_pyarrow()
    if not raw.content:
        return None
    with pa.ipc.open_stream(pa.BufferReader(raw.content)) as reader:
        return reader.read_all()


def decode_arrow_page(
    raw: RawResponse,
    validate: Callable[[dict[str, Any]], T | None],
) -> Paginated[T]:
    """Decode an Arrow IPC stream list response into ``Paginated[T]``.

    ``validate`` maps one decoded row dict onto a record model (e.g. a
    model's ``model_validate`` or a ``TypeAdapter.validate_python``); it
    may return ``None`` to skip a row (unknown-family tolerance). Row
    values come from the columnar body — nested struct columns (the typed
    event ``payload``) decode to nested dicts via ``to_pylist()``, so the
    same validator serves JSON and Arrow. ``next`` / ``count`` /
    ``total_count`` are read back from the ``X-Next-Cursor`` /
    ``X-Result-Count`` / ``X-Total-Count`` response headers so the resulting
    envelope is indistinguishable from the JSON path and pages identically.
    """
    table = decode_arrow_table(raw)
    rows: list[dict[str, Any]] = table.to_pylist() if table is not None else []
    records = [
        record
        for record in (validate(row) for row in rows)
        if record is not None
    ]

    headers = raw.headers
    count_header = headers.get("X-Result-Count") or headers.get(
        "x-result-count"
    )
    total_header = headers.get("X-Total-Count") or headers.get("x-total-count")
    page: Paginated[T] = Paginated(
        records=records,
        count=int(count_header) if count_header is not None else len(records),
        total_count=int(total_header) if total_header is not None else None,
        next=next_cursor_header(raw),
    )
    return page


class ArrowPageIterator:
    """Lazily iterate a list read as one ``pyarrow.Table`` per page.

    Yields each server page as a Table (constant memory — one page held
    at a time), driving the same opaque ``X-Next-Cursor`` token the JSON
    pager uses. Empty pages (no body) yield nothing. :meth:`read_all`
    concatenates every page into a single Table.
    """

    def __init__(
        self,
        fetch: Callable[[str | None], RawResponse],
        *,
        start: str | None = None,
    ) -> None:
        self._fetch = fetch
        self._start = start

    def __iter__(self) -> Iterator[pa.Table]:
        cursor = self._start
        while True:
            raw = self._fetch(cursor)
            table = decode_arrow_table(raw)
            if table is not None:
                yield table
            cursor = next_cursor_header(raw)
            if cursor is None:
                return

    def read_all(self) -> pa.Table:
        """Fetch every page and concatenate into one ``pyarrow.Table``."""
        pa = import_pyarrow()
        tables = list(self)
        if not tables:
            return pa.table({})
        return pa.concat_tables(tables)


class AsyncArrowPageIterator:
    """Async twin of :class:`ArrowPageIterator`."""

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
