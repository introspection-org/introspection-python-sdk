"""Async twins re-exported by :mod:`introspection_sdk.resources.recipes`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.recipes import Recipe


class AsyncRecipes:
    """CP ``/v1/recipes`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    # --- reads --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID | None = None,
        repository_id: UUID | None = None,
        name: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Recipe, Paginated[Recipe]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List recipes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every recipe across
        pages."""
        # unasync: end
        """List recipes. Iterate the returned :class:`Pager` to stream every
        recipe across pages, or call ``.page()`` for the first page only."""

        async def fetch(cursor: str | None) -> Paginated[Recipe]:
            params: dict[str, Any] = {
                "project": str(project) if project else None,
                "repository_id": (
                    str(repository_id) if repository_id is not None else None
                ),
                "name": name,
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/recipes", params=params
            )
            return Paginated[Recipe].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, recipe_id: UUID) -> Recipe:
        payload = await self._http.request("GET", f"/v1/recipes/{recipe_id}")
        return Recipe.model_validate(payload)
