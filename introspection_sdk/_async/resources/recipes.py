"""Re-exported by :mod:`introspection_sdk.resources.recipes`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from introspection_sdk._async.resources._crud import _body, _project
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.recipes import (
    Recipe,
    RecipeCreate,
    RecipeUpdate,
)


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

    # --- writes -------------------------------------------------------

    async def create(
        self,
        *,
        project: str | UUID,
        repository_id: UUID | str,
        name: str,
        git_ref: str | None = None,
        git_commit_sha: str | None = None,
        git_commit_subject: str | None = None,
        sub_path: str | None = None,
        slug: str | None = None,
        description: str | None = None,
    ) -> Recipe:
        """Pin a recipe to a commit of ``repository_id``.

        ``git_commit_sha`` is the 40-character commit and ``git_ref`` the
        branch, tag or short sha it was picked from. ``slug`` is derived
        from ``name`` and the short sha when omitted; ``sub_path`` points
        into a monorepo.
        """
        body = _body(
            RecipeCreate,
            {
                "project": str(project),
                "repository_id": repository_id,
                "name": name,
                "git_ref": git_ref,
                "git_commit_sha": git_commit_sha,
                "git_commit_subject": git_commit_subject,
                "sub_path": sub_path,
                "slug": slug,
                "description": description,
            },
        )
        payload = await self._http.request("POST", "/v1/recipes", json=body)
        return Recipe.model_validate(payload)

    async def update(
        self,
        recipe_id: UUID | str,
        *,
        project: str | UUID | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Recipe:
        """Rename or redescribe a recipe; only the fields given are sent."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/recipes/{recipe_id}",
            params=_project(project),
            json=_body(
                RecipeUpdate, {"name": name, "description": description}
            ),
        )
        return Recipe.model_validate(payload)

    async def delete(
        self, recipe_id: UUID | str, *, project: str | UUID | None = None
    ) -> None:
        await self._http.request(
            "DELETE",
            f"/v1/recipes/{recipe_id}",
            params=_project(project),
            expect="empty",
        )
