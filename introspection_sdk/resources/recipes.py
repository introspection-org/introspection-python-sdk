"""``client.recipes`` — CP CRUD namespace for ``/v1/recipes``.

Pure CRUD, no handle subtype. Recipes are immutable snapshots of a
git repository at a specific commit; runtimes / experiment arms refer
to recipes by id. See ``introspection-cloud/docs/design/sdk-api.md``
section "Recipes — `client.recipes` (CP)".
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _HttpClient
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
        project_id: str | UUID,
        repository_id: str | UUID | None = None,
        name: str | None = None,
        git_ref: str | None = None,
        git_commit_sha: str | None = None,
        limit: int | None = None,
        next: str | None = None,
        include_total: bool | None = None,
    ) -> Paginated[Recipe]:
        params: dict[str, Any] = {
            "project_id": str(project_id),
            "repository_id": (
                str(repository_id) if repository_id is not None else None
            ),
            "name": name,
            "git_ref": git_ref,
            "git_commit_sha": git_commit_sha,
            "limit": limit,
            "next": next,
            "include_total": include_total,
        }
        payload = self._http.request("GET", "/v1/recipes", params=params)
        return Paginated[Recipe].model_validate(payload)

    def iter(self, **filters: Any) -> Iterator[Recipe]:
        next_token: str | None = filters.pop("next", None)
        while True:
            page = self.list(next=next_token, **filters)
            yield from page.records
            if not page.next:
                return
            next_token = page.next

    def get(self, recipe_id: str | UUID) -> Recipe:
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
        recipe_id: str | UUID,
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

    def delete(self, recipe_id: str | UUID) -> None:
        self._http.request(
            "DELETE",
            f"/v1/recipes/{recipe_id}",
            expect="empty",
        )


__all__ = ["Recipes"]
