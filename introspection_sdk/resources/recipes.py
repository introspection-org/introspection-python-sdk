"""``client.recipes`` — CP read namespace for ``/v1/recipes``.

Read-only, no handle subtype. A runner resolves the recipe it is running
under; authoring one is a project-authoring act and lives in the CLI.
Recipes are immutable snapshots of a git repository at a specific commit;
runtimes / experiment arms refer to recipes by id.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.recipes import Recipe


class Recipes:
    """CP ``/v1/recipes`` namespace."""

    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    # --- reads --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID | None = None,
        repository_id: UUID | None = None,
        name: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Recipe, Paginated[Recipe]]:
        """List recipes. Iterate the returned :class:`Pager` to stream every
        recipe across pages, or call ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[Recipe]:
            params: dict[str, Any] = {
                "project": str(project) if project else None,
                "repository_id": (
                    str(repository_id) if repository_id is not None else None
                ),
                "name": name,
                "limit": limit,
                "next": cursor,
            }
            payload = self._http.request("GET", "/v1/recipes", params=params)
            return Paginated[Recipe].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(self, recipe_id: UUID) -> Recipe:
        payload = self._http.request("GET", f"/v1/recipes/{recipe_id}")
        return Recipe.model_validate(payload)


class AsyncRecipes:
    """Async twin of :class:`Recipes` (CP ``/v1/recipes``)."""

    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

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
        """List recipes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every recipe across
        pages."""

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
