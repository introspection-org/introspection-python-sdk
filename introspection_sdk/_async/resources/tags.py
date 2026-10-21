"""Async twins re-exported by :mod:`introspection_sdk.resources.tags`."""

from __future__ import annotations

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.resources._tags_common import (
    _create_body,
    _path,
    _update_body,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tags import (
    Tag,
    TagCreate,
    TagKind,
    TagUpdate,
)


class AsyncTags:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        kind: TagKind,
        *,
        search: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Tag, Paginated[Tag]]:
        """List one catalogue. `kind` is required: no listing spans both."""

        async def fetch(cursor: str | None) -> Paginated[Tag]:
            payload = await self._http.request(
                "GET",
                "/v1/tags",
                params={
                    "kind": kind.value,
                    "search": search,
                    "limit": limit,
                    "next": cursor,
                },
            )
            return Paginated[Tag].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(self, tag: TagCreate) -> Tag:
        """Add a tag. An existing one comes back as it is, a deleted one revives."""
        return Tag.model_validate(
            await self._http.request(
                "POST", "/v1/tags", json=_create_body(tag)
            )
        )

    async def get(self, kind: TagKind, name: str) -> Tag:
        return Tag.model_validate(
            await self._http.request("GET", _path(kind, name))
        )

    async def update(self, kind: TagKind, name: str, patch: TagUpdate) -> Tag:
        return Tag.model_validate(
            await self._http.request(
                "PATCH", _path(kind, name), json=_update_body(kind, patch)
            )
        )

    async def delete(self, kind: TagKind, name: str) -> None:
        """Remove a tag from the catalogue. Shares, member tags and annotations keep theirs."""
        await self._http.request("DELETE", _path(kind, name), expect="empty")
