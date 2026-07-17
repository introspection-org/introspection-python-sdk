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
  Arrow IPC *stream* (row values only) with the pagination metadata on
  response headers. :func:`decode_arrow_page` rebuilds the identical
  :class:`~introspection_sdk.schemas.pagination.Paginated` envelope the JSON
  path produces, so the auto-paging ``Pager`` drives both formats
  unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from introspection_sdk._http import RawResponse
from introspection_sdk.schemas.pagination import Paginated

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


def decode_arrow_page(
    raw: RawResponse,
    validate: Callable[[dict[str, Any]], T],
) -> Paginated[T]:
    """Decode an Arrow IPC stream list response into ``Paginated[T]``.

    ``validate`` maps one decoded row dict onto a record model (e.g. a
    model's ``model_validate`` or a ``TypeAdapter.validate_python``). Row
    values come from the columnar body; ``next`` / ``count`` /
    ``total_count`` are read back from the ``X-Next-Cursor`` /
    ``X-Result-Count`` / ``X-Total-Count`` response headers so the resulting
    envelope is indistinguishable from the JSON path and pages identically.
    """
    try:
        import pyarrow as pa
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "format='arrow' requires the 'pyarrow' package. Install it with "
            "`pip install pyarrow` (or `pip install introspection-sdk[arrow]`)."
        ) from exc

    headers = raw.headers
    rows: list[dict[str, Any]] = []
    if raw.content:
        with pa.ipc.open_stream(pa.BufferReader(raw.content)) as reader:
            rows = reader.read_all().to_pylist()
    records = [validate(row) for row in rows]

    count_header = headers.get("X-Result-Count") or headers.get(
        "x-result-count"
    )
    total_header = headers.get("X-Total-Count") or headers.get("x-total-count")
    next_cursor = headers.get("X-Next-Cursor") or headers.get("x-next-cursor")
    page: Paginated[T] = Paginated(
        records=records,
        count=int(count_header) if count_header is not None else len(records),
        total_count=int(total_header) if total_header is not None else None,
        next=next_cursor or None,
    )
    return page
