"""`runner.annotations.*` namespace: expert-distillation open coding.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT. Annotations
are open-coding rows over conversations: reviews, marks and dataset
memberships, each optionally anchored to a text selection.
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
from introspection_sdk.schemas.annotations import (
    Annotation,
    AnnotationCreateRequest,
    AnnotationKind,
    AnnotationSelection,
    AnnotationUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    include_total: bool,
    kind: AnnotationKind | str | None,
    member_id: str | None,
    conversation_id: str | None,
    dataset_id: str | None,
    parent_id: str | None,
    pending: bool | None,
    label: str | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "include_total": include_total,
        "kind": (kind.value if isinstance(kind, AnnotationKind) else kind),
        "member_id": member_id,
        "conversation_id": conversation_id,
        "dataset_id": dataset_id,
        "parent_id": parent_id,
        "pending": pending,
        "label": label,
    }


def _create_body(
    *,
    conversation_id: str,
    kind: AnnotationKind | str,
    member_id: str | None,
    parent_id: str | None,
    selection: AnnotationSelection | dict[str, Any] | None,
    labels: list[str] | None,
    comment: str | None,
    dataset_id: str | None,
) -> dict[str, Any]:
    # Loose public inputs (plain str / enum / dict) are coerced by
    # validation: str -> AnnotationKind, str -> UUID for the id fields,
    # dict -> AnnotationSelection.
    return AnnotationCreateRequest.model_validate(
        {
            "conversation_id": conversation_id,
            "kind": kind,
            "member_id": member_id,
            "parent_id": parent_id,
            "selection": selection,
            "labels": labels,
            "comment": comment,
            "dataset_id": dataset_id,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    labels: list[str] | None,
    comment: str | None,
    selection: AnnotationSelection | dict[str, Any] | None,
    completed: bool | None,
) -> dict[str, Any]:
    # `exclude_none` drops an omitted label list but keeps an explicit
    # [], which is what clears the labels — they replace wholesale.
    return AnnotationUpdateRequest.model_validate(
        {
            "labels": labels,
            "comment": comment,
            "selection": selection,
            "completed": completed,
        }
    ).model_dump(mode="json", exclude_none=True)


class Annotations:
    """Synchronous `/v1/annotations` resource."""

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        kind: AnnotationKind | str | None = None,
        member_id: str | None = None,
        conversation_id: str | None = None,
        dataset_id: str | None = None,
        parent_id: str | None = None,
        pending: bool | None = None,
        label: str | None = None,
    ) -> Pager[Annotation, Paginated[Annotation]]:
        """List annotations. Iterate the returned :class:`Pager` to
        stream every annotation across pages, or call ``.page()`` for
        the first page only."""

        def fetch(cursor: str | None) -> Paginated[Annotation]:
            payload = self._http.request(
                "GET",
                "/v1/annotations",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    include_total=include_total,
                    kind=kind,
                    member_id=member_id,
                    conversation_id=conversation_id,
                    dataset_id=dataset_id,
                    parent_id=parent_id,
                    pending=pending,
                    label=label,
                ),
            )
            return Paginated[Annotation].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        conversation_id: str,
        kind: AnnotationKind | str,
        member_id: str | None = None,
        parent_id: str | None = None,
        selection: AnnotationSelection | dict[str, Any] | None = None,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        dataset_id: str | None = None,
    ) -> Annotation:
        """Create an annotation. Pending-review/membership creates are
        idempotent — a repeat create returns the existing row."""
        payload = self._http.request(
            "POST",
            "/v1/annotations",
            json=_create_body(
                conversation_id=conversation_id,
                kind=kind,
                member_id=member_id,
                parent_id=parent_id,
                selection=selection,
                labels=labels,
                comment=comment,
                dataset_id=dataset_id,
            ),
        )
        return Annotation.model_validate(payload)

    def get(self, annotation_id: str) -> Annotation:
        payload = self._http.request("GET", f"/v1/annotations/{annotation_id}")
        return Annotation.model_validate(payload)

    def update(
        self,
        annotation_id: str,
        *,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        selection: AnnotationSelection | dict[str, Any] | None = None,
        completed: bool | None = None,
    ) -> Annotation:
        """Update an annotation (owner-only server-side). ``labels``
        replaces wholesale — ``[]`` clears, omit to leave alone."""
        payload = self._http.request(
            "PATCH",
            f"/v1/annotations/{annotation_id}",
            json=_update_body(
                labels=labels,
                comment=comment,
                selection=selection,
                completed=completed,
            ),
        )
        return Annotation.model_validate(payload)

    def delete(self, annotation_id: str) -> None:
        self._http.request(
            "DELETE", f"/v1/annotations/{annotation_id}", expect="empty"
        )


class AsyncAnnotations:
    """Asynchronous `/v1/annotations` resource."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        kind: AnnotationKind | str | None = None,
        member_id: str | None = None,
        conversation_id: str | None = None,
        dataset_id: str | None = None,
        parent_id: str | None = None,
        pending: bool | None = None,
        label: str | None = None,
    ) -> AsyncPager[Annotation, Paginated[Annotation]]:
        """List annotations. ``await`` the returned :class:`AsyncPager`
        for the first page, or ``async for`` it to stream every
        annotation across pages."""

        async def fetch(cursor: str | None) -> Paginated[Annotation]:
            payload = await self._http.request(
                "GET",
                "/v1/annotations",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    include_total=include_total,
                    kind=kind,
                    member_id=member_id,
                    conversation_id=conversation_id,
                    dataset_id=dataset_id,
                    parent_id=parent_id,
                    pending=pending,
                    label=label,
                ),
            )
            return Paginated[Annotation].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        conversation_id: str,
        kind: AnnotationKind | str,
        member_id: str | None = None,
        parent_id: str | None = None,
        selection: AnnotationSelection | dict[str, Any] | None = None,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        dataset_id: str | None = None,
    ) -> Annotation:
        """Create an annotation. Pending-review/membership creates are
        idempotent — a repeat create returns the existing row."""
        payload = await self._http.request(
            "POST",
            "/v1/annotations",
            json=_create_body(
                conversation_id=conversation_id,
                kind=kind,
                member_id=member_id,
                parent_id=parent_id,
                selection=selection,
                labels=labels,
                comment=comment,
                dataset_id=dataset_id,
            ),
        )
        return Annotation.model_validate(payload)

    async def get(self, annotation_id: str) -> Annotation:
        payload = await self._http.request(
            "GET", f"/v1/annotations/{annotation_id}"
        )
        return Annotation.model_validate(payload)

    async def update(
        self,
        annotation_id: str,
        *,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        selection: AnnotationSelection | dict[str, Any] | None = None,
        completed: bool | None = None,
    ) -> Annotation:
        """Update an annotation (owner-only server-side). ``labels``
        replaces wholesale — ``[]`` clears, omit to leave alone."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/annotations/{annotation_id}",
            json=_update_body(
                labels=labels,
                comment=comment,
                selection=selection,
                completed=completed,
            ),
        )
        return Annotation.model_validate(payload)

    async def delete(self, annotation_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/annotations/{annotation_id}", expect="empty"
        )
