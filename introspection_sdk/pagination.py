"""Lazy, auto-paging collection returned by every ``list()`` method.

The Python sibling of the JS SDK's ``Paginator`` (``pagination.ts``).
A :class:`Pager` is the single object every ``list()`` returns. It is

* **iterable** — iterate it (``for item in listing``) to stream every
  item across all pages, fetching each page only as the iterator reaches
  it; stop early to stop fetching; and
* **a first-page handle** — call :meth:`Pager.page` to get the first page
  with its wire-envelope metadata intact (counts, cursors, ``has_more``,
  …). This mirrors ``await listing`` in the async JS SDK; the first page
  is fetched once and cached.

Two wire protocols are adapted through the same :class:`Pager` via the
``items`` / ``next_cursor`` callbacks:

* the standard Introspection cursor envelope
  (:class:`~introspection_sdk.schemas.pagination.Paginated`) — items live
  in ``records`` and the next page is the opaque ``next`` token
  (:func:`cursor_paginate`); and
* the OpenAI-style ``after`` / ``has_more`` envelope — items live in
  ``data`` and the next cursor is the previous page's ``last_id`` while
  ``has_more`` is true (:func:`after_paginate`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Generic, TypeVar

from introspection_sdk.schemas.pagination import Paginated

T = TypeVar("T")
TPage = TypeVar("TPage")


class Pager(Generic[T, TPage]):
    """A lazy, auto-paging view over a paginated list endpoint."""

    def __init__(
        self,
        fetch: Callable[[str | None], TPage],
        *,
        items: Callable[[TPage], list[T]],
        next_cursor: Callable[[TPage], str | None],
        start: str | None = None,
    ) -> None:
        self._fetch = fetch
        self._items = items
        self._next = next_cursor
        self._start = start
        self._first: TPage | None = None

    def page(self) -> TPage:
        """Return the first page, fetched once and cached.

        The full wire envelope is preserved, so metadata like
        ``total_count`` / ``has_more`` is available without iterating.
        """
        if self._first is None:
            self._first = self._fetch(self._start)
        return self._first

    def __iter__(self) -> Iterator[T]:
        page = self.page()
        while True:
            yield from self._items(page)
            cursor = self._next(page)
            if cursor is None:
                return
            page = self._fetch(cursor)

    def __getattr__(self, name: str) -> Any:
        # Proxy first-page envelope fields (``records`` / ``next`` /
        # ``data`` / ``has_more`` / ``total_count`` / …) so a Pager can be
        # used wherever the raw page was, on top of being iterable. The
        # leading-underscore guard keeps private/dunder lookups (and the
        # ``self._*`` attributes set in ``__init__``) off the network path
        # and prevents recursion.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.page(), name)


def cursor_paginate(
    fetch: Callable[[str | None], Paginated[T]],
    *,
    start: str | None = None,
) -> Pager[T, Paginated[T]]:
    """Build a :class:`Pager` over the standard cursor envelope: items in
    ``records``, next page via the opaque ``next`` token."""
    return Pager(
        fetch,
        items=lambda page: page.records,
        next_cursor=lambda page: page.next,
        start=start,
    )


def after_paginate(
    fetch: Callable[[str | None], TPage],
    *,
    items: Callable[[TPage], list[T]],
    last_id: Callable[[TPage], str | None],
    has_more: Callable[[TPage], bool],
    start: str | None = None,
) -> Pager[T, TPage]:
    """Build a :class:`Pager` over an OpenAI-style ``after`` / ``has_more``
    envelope: page forward by passing the previous page's ``last_id`` as
    ``after`` while ``has_more`` is true."""

    def next_cursor(page: TPage) -> str | None:
        tail = last_id(page)
        return tail if has_more(page) and tail is not None else None

    return Pager(fetch, items=items, next_cursor=next_cursor, start=start)


__all__ = ["Pager", "after_paginate", "cursor_paginate"]
