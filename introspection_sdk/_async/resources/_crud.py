"""Request plumbing the administration namespaces share."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated

M = TypeVar("M", bound=BaseModel)


def _project(project: str | UUID | None) -> dict[str, Any]:
    """The ``?project=`` selector (slug or id), sent only when given; needed
    when the credential does not already name a project."""
    return {"project": str(project) if project is not None else None}


def _body(request: type[BaseModel], fields: dict[str, Any]) -> dict[str, Any]:
    """Validate ``fields`` against the request model and drop the unset ones,
    so an omitted field never reaches the wire as ``null``."""
    return request.model_validate(fields).model_dump(
        mode="json", exclude_none=True
    )


class _AsyncResource:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def _paginate(
        self,
        path: str,
        page: type[Paginated[M]],
        params: dict[str, Any],
    ) -> AsyncPager[M, Paginated[M]]:
        start = params.pop("next", None)

        async def fetch(cursor: str | None) -> Paginated[M]:
            payload = await self._http.request(
                "GET", path, params={**params, "next": cursor}
            )
            return page.model_validate(payload)

        return async_cursor_paginate(fetch, start=start)

    async def _call(
        self,
        method: str,
        path: str,
        response: type[M],
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> M:
        payload = await self._http.request(
            method, path, params=params, json=json
        )
        return response.model_validate(payload)

    async def _delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> None:
        await self._http.request("DELETE", path, params=params, expect="empty")
