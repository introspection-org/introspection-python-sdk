"""The project tag catalogue: the values a share, a member tag, or an annotation carries."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import TypeAdapter

from introspection_sdk._errors import ValidationError
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tags import (
    Tag,
    TagCreate,
    TagKind,
    TagUpdate,
)

_CREATE: TypeAdapter[TagCreate] = TypeAdapter(TagCreate)


def _path(kind: TagKind, name: str) -> str:
    # An access tag's name may contain `/`, so it is encoded even though the
    # API matches it as a path.
    return f"/v1/tags/{kind.value}/{quote(name, safe='')}"


def _create_body(tag: TagCreate) -> dict[str, object]:
    validated = _CREATE.validate_python(tag)
    return validated.model_dump(mode="json", exclude_none=True)


def _update_body(kind: TagKind, patch: TagUpdate) -> dict[str, object]:
    fields = patch.model_fields_set
    if not fields:
        raise ValidationError(
            "A tag update must name a color or a description",
            status_code=422,
            code="invalid_tag_update",
        )
    if kind is TagKind.ACCESS and "color" in fields:
        raise ValidationError(
            "An access tag has no color",
            status_code=422,
            code="invalid_tag_color",
        )
    # `exclude_unset` so an omitted description stays omitted: the API reads a
    # null as "clear it" and an absent key as "leave it".
    return patch.model_dump(mode="json", exclude_unset=True)


class Tags:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        kind: TagKind,
        *,
        search: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Tag, Paginated[Tag]]:
        """List one catalogue. `kind` is required: no listing spans both."""

        def fetch(cursor: str | None) -> Paginated[Tag]:
            payload = self._http.request(
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

        return cursor_paginate(fetch, start=next)

    def create(self, tag: TagCreate) -> Tag:
        """Add a tag. An existing one comes back as it is, a deleted one revives."""
        return Tag.model_validate(
            self._http.request("POST", "/v1/tags", json=_create_body(tag))
        )

    def get(self, kind: TagKind, name: str) -> Tag:
        return Tag.model_validate(self._http.request("GET", _path(kind, name)))

    def update(self, kind: TagKind, name: str, patch: TagUpdate) -> Tag:
        return Tag.model_validate(
            self._http.request(
                "PATCH", _path(kind, name), json=_update_body(kind, patch)
            )
        )

    def delete(self, kind: TagKind, name: str) -> None:
        """Remove a tag from the catalogue. Shares, member tags and annotations keep theirs."""
        self._http.request("DELETE", _path(kind, name), expect="empty")


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


__all__ = ["AsyncTags", "Tags"]
