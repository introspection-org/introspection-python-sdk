"""``client.recipes`` — CP CRUD namespace for ``/v1/recipes``.

Pure CRUD, no handle subtype. Recipes are immutable snapshots of a
git repository at a specific commit; runtimes / experiment arms refer
to recipes by id. See ``introspection-cloud/docs/design/sdk-api.md``
section "Recipes — `client.recipes` (CP)".
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
from introspection_sdk.schemas.recipes import (
    Recipe,
    RecipeCreate,
    RecipeUpdate,
)


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

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID,
        repository_id: UUID | None = None,
        name: str | None = None,
        git_ref: str | None = None,
        git_commit_sha: str | None = None,
        limit: int | None = None,
        next: str | None = None,
        include_total: bool | None = None,
    ) -> Pager[Recipe, Paginated[Recipe]]:
        """List recipes. Iterate the returned :class:`Pager` to stream every
        recipe across pages, or call ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[Recipe]:
            params: dict[str, Any] = {
                "project": str(project),
                "repository_id": (
                    str(repository_id) if repository_id is not None else None
                ),
                "name": name,
                "git_ref": git_ref,
                "git_commit_sha": git_commit_sha,
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            payload = self._http.request("GET", "/v1/recipes", params=params)
            return Paginated[Recipe].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(self, recipe_id: UUID) -> Recipe:
        payload = self._http.request("GET", f"/v1/recipes/{recipe_id}")
        return Recipe.model_validate(payload)

    def create(self, input: RecipeCreate | dict[str, Any]) -> Recipe:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RecipeCreate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = self._http.request("POST", "/v1/recipes", json=body)
        return Recipe.model_validate(payload)

    def update(
        self,
        recipe_id: UUID,
        patch: RecipeUpdate | dict[str, Any],
    ) -> Recipe:
        body = (
            patch.model_dump(exclude_none=True, mode="json")
            if isinstance(patch, RecipeUpdate)
            else {k: v for k, v in patch.items() if v is not None}
        )
        payload = self._http.request(
            "PATCH", f"/v1/recipes/{recipe_id}", json=body
        )
        return Recipe.model_validate(payload)

    def delete(self, recipe_id: UUID) -> None:
        self._http.request(
            "DELETE",
            f"/v1/recipes/{recipe_id}",
            expect="empty",
        )


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

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID,
        repository_id: UUID | None = None,
        name: str | None = None,
        git_ref: str | None = None,
        git_commit_sha: str | None = None,
        limit: int | None = None,
        next: str | None = None,
        include_total: bool | None = None,
    ) -> AsyncPager[Recipe, Paginated[Recipe]]:
        """List recipes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every recipe across
        pages."""

        async def fetch(cursor: str | None) -> Paginated[Recipe]:
            params: dict[str, Any] = {
                "project": str(project),
                "repository_id": (
                    str(repository_id) if repository_id is not None else None
                ),
                "name": name,
                "git_ref": git_ref,
                "git_commit_sha": git_commit_sha,
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            payload = await self._http.request(
                "GET", "/v1/recipes", params=params
            )
            return Paginated[Recipe].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, recipe_id: UUID) -> Recipe:
        payload = await self._http.request("GET", f"/v1/recipes/{recipe_id}")
        return Recipe.model_validate(payload)

    async def create(self, input: RecipeCreate | dict[str, Any]) -> Recipe:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RecipeCreate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = await self._http.request("POST", "/v1/recipes", json=body)
        return Recipe.model_validate(payload)

    async def update(
        self,
        recipe_id: UUID,
        patch: RecipeUpdate | dict[str, Any],
    ) -> Recipe:
        body = (
            patch.model_dump(exclude_none=True, mode="json")
            if isinstance(patch, RecipeUpdate)
            else {k: v for k, v in patch.items() if v is not None}
        )
        payload = await self._http.request(
            "PATCH", f"/v1/recipes/{recipe_id}", json=body
        )
        return Recipe.model_validate(payload)

    async def delete(self, recipe_id: UUID) -> None:
        await self._http.request(
            "DELETE",
            f"/v1/recipes/{recipe_id}",
            expect="empty",
        )


__all__ = ["AsyncRecipes", "Recipes"]
