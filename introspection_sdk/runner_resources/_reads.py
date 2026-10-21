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
* **Columnar page iteration.** The ``.list_arrow()`` accessors return an
  :class:`ArrowPageIterator` / :class:`AsyncArrowPageIterator` yielding one
  ``pyarrow.Table`` per server page (constant memory), with a
  ``read_all()`` convenience concatenating every page into one Table.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources._reads import (
    ARROW_ACCEPT_HEADERS,
    ARROW_STREAM_MEDIA_TYPE,
    LOOKBACK_RE,
    LOOKBACK_UNITS,
    TRAJECTORY_ACCEPT_HEADERS,
    TRAJECTORY_MEDIA_TYPE,
    AsyncArrowPageIterator,
    ReadFormat,
    T,
    decode_arrow_page,
    decode_arrow_table,
    import_pyarrow,
    next_cursor_header,
    parse_lookback,
    resolve_window,
)
from introspection_sdk._sync.runner_resources._reads import (
    ArrowPageIterator,
)

__all__ = [
    "ARROW_ACCEPT_HEADERS",
    "ARROW_STREAM_MEDIA_TYPE",
    "ArrowPageIterator",
    "AsyncArrowPageIterator",
    "LOOKBACK_RE",
    "LOOKBACK_UNITS",
    "ReadFormat",
    "T",
    "TRAJECTORY_ACCEPT_HEADERS",
    "TRAJECTORY_MEDIA_TYPE",
    "decode_arrow_page",
    "decode_arrow_table",
    "import_pyarrow",
    "next_cursor_header",
    "parse_lookback",
    "resolve_window",
]
