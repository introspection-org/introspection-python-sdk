"""`runner.datasets.*` namespace: saved label filters over annotations.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT. A dataset
is a named label predicate (a saved filter) over annotations — there
are no memberships: passing ``dataset_id`` to
``runner.annotations.list(...)`` applies the dataset's predicate.
"""

from __future__ import annotations

import builtins
from typing import Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.datasets import (
    Dataset,
    DatasetCreateRequest,
    DatasetUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    slug: str | None,
    created_by_member_id: str | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "slug": slug,
        "created_by_member_id": created_by_member_id,
    }


def _create_body(
    *,
    slug: str,
    labels: list[str],
    description: str | None,
) -> dict[str, Any]:
    return DatasetCreateRequest.model_validate(
        {
            "slug": slug,
            "labels": labels,
            "description": description,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    description: str | None,
    labels: list[str] | None,
) -> dict[str, Any]:
    return DatasetUpdateRequest.model_validate(
        {
            "description": description,
            "labels": labels,
        }
    ).model_dump(mode="json", exclude_none=True)


class Datasets:
    """Synchronous `/v1/datasets` resource."""

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        slug: str | None = None,
        created_by_member_id: str | None = None,
    ) -> Pager[Dataset, Paginated[Dataset]]:
        """List datasets. Iterate the returned :class:`Pager` to stream
        every dataset across pages, or call ``.page()`` for the first
        page only."""

        def fetch(cursor: str | None) -> Paginated[Dataset]:
            payload = self._http.request(
                "GET",
                "/v1/datasets",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    slug=slug,
                    created_by_member_id=created_by_member_id,
                ),
            )
            return Paginated[Dataset].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        slug: str,
        labels: builtins.list[str],
        description: str | None = None,
    ) -> Dataset:
        """Create a dataset. ``labels`` is the saved predicate (at
        least one, normalized server-side). The server slugifies
        ``slug``; create is idempotent on the live slug."""
        payload = self._http.request(
            "POST",
            "/v1/datasets",
            json=_create_body(
                slug=slug, labels=labels, description=description
            ),
        )
        return Dataset.model_validate(payload)

    def get(self, dataset_id: str) -> Dataset:
        payload = self._http.request("GET", f"/v1/datasets/{dataset_id}")
        return Dataset.model_validate(payload)

    def update(
        self,
        dataset_id: str,
        *,
        description: str | None = None,
        labels: builtins.list[str] | None = None,
    ) -> Dataset:
        """Update a dataset. ``labels`` replaces the predicate and must
        keep at least one entry when passed."""
        payload = self._http.request(
            "PATCH",
            f"/v1/datasets/{dataset_id}",
            json=_update_body(description=description, labels=labels),
        )
        return Dataset.model_validate(payload)

    def delete(self, dataset_id: str) -> None:
        self._http.request(
            "DELETE", f"/v1/datasets/{dataset_id}", expect="empty"
        )


class AsyncDatasets:
    """Asynchronous `/v1/datasets` resource."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        slug: str | None = None,
        created_by_member_id: str | None = None,
    ) -> AsyncPager[Dataset, Paginated[Dataset]]:
        """List datasets. ``await`` the returned :class:`AsyncPager` for
        the first page, or ``async for`` it to stream every dataset
        across pages."""

        async def fetch(cursor: str | None) -> Paginated[Dataset]:
            payload = await self._http.request(
                "GET",
                "/v1/datasets",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    slug=slug,
                    created_by_member_id=created_by_member_id,
                ),
            )
            return Paginated[Dataset].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        slug: str,
        labels: builtins.list[str],
        description: str | None = None,
    ) -> Dataset:
        """Create a dataset. ``labels`` is the saved predicate (at
        least one, normalized server-side). The server slugifies
        ``slug``; create is idempotent on the live slug."""
        payload = await self._http.request(
            "POST",
            "/v1/datasets",
            json=_create_body(
                slug=slug, labels=labels, description=description
            ),
        )
        return Dataset.model_validate(payload)

    async def get(self, dataset_id: str) -> Dataset:
        payload = await self._http.request("GET", f"/v1/datasets/{dataset_id}")
        return Dataset.model_validate(payload)

    async def update(
        self,
        dataset_id: str,
        *,
        description: str | None = None,
        labels: builtins.list[str] | None = None,
    ) -> Dataset:
        """Update a dataset. ``labels`` replaces the predicate and must
        keep at least one entry when passed."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/datasets/{dataset_id}",
            json=_update_body(description=description, labels=labels),
        )
        return Dataset.model_validate(payload)

    async def delete(self, dataset_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/datasets/{dataset_id}", expect="empty"
        )
