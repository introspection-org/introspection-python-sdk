"""`runner.annotations.*` namespace: span annotations.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT. An
annotation is one member's labels + comment on one OpenTelemetry
span (addressed by ``trace_id`` + ``span_id``); a row with no
``completed_at`` is a pending review.
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
    AnnotationUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    include_total: bool,
    member_id: str | None,
    trace_id: str | None,
    span_id: str | None,
    dataset_id: str | None,
    pending: bool | None,
    label: str | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "include_total": include_total,
        "member_id": member_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "dataset_id": dataset_id,
        "pending": pending,
        "label": label,
    }


def _create_body(
    *,
    trace_id: str,
    span_id: str,
    member_id: str | None,
    labels: list[str] | None,
    comment: str | None,
    completed: bool | None,
) -> dict[str, Any]:
    # Loose public inputs are coerced by validation (str -> UUID for
    # member_id). `exclude_none` keeps omitted optionals off the wire,
    # so the server's defaults apply (notably `completed`, which
    # defaults to true there — an explicit False creates a pending
    # review and must survive the dump).
    return AnnotationCreateRequest.model_validate(
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "member_id": member_id,
            "labels": labels,
            "comment": comment,
            "completed": completed,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    labels: list[str] | None,
    comment: str | None,
    completed: bool | None,
) -> dict[str, Any]:
    # `exclude_none` drops an omitted label list but keeps an explicit
    # [], which is what clears the labels — they replace wholesale.
    return AnnotationUpdateRequest.model_validate(
        {
            "labels": labels,
            "comment": comment,
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
        member_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataset_id: str | None = None,
        pending: bool | None = None,
        label: str | None = None,
    ) -> Pager[Annotation, Paginated[Annotation]]:
        """List annotations. ``dataset_id`` applies that dataset's
        saved label predicate (a filter, not a membership). Iterate
        the returned :class:`Pager` to stream every annotation across
        pages, or call ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[Annotation]:
            payload = self._http.request(
                "GET",
                "/v1/annotations",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    include_total=include_total,
                    member_id=member_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    dataset_id=dataset_id,
                    pending=pending,
                    label=label,
                ),
            )
            return Paginated[Annotation].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        trace_id: str,
        span_id: str,
        member_id: str | None = None,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        completed: bool | None = None,
    ) -> Annotation:
        """Annotate a span. ``member_id`` names the assignee — a
        foreign member requires a privileged caller and empty
        ``labels``/``comment``, and the row is forced pending.
        ``completed`` defaults to true server-side; pass ``False`` to
        create a pending review. Labels are normalized server-side
        (slugified, deduped, sorted)."""
        payload = self._http.request(
            "POST",
            "/v1/annotations",
            json=_create_body(
                trace_id=trace_id,
                span_id=span_id,
                member_id=member_id,
                labels=labels,
                comment=comment,
                completed=completed,
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
        completed: bool | None = None,
    ) -> Annotation:
        """Update an annotation (owner-only server-side). ``labels``
        replaces wholesale and is normalized — ``[]`` clears, omit to
        leave alone. ``completed=True`` stamps ``completed_at``,
        ``False`` clears it back to pending."""
        payload = self._http.request(
            "PATCH",
            f"/v1/annotations/{annotation_id}",
            json=_update_body(
                labels=labels,
                comment=comment,
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
        member_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataset_id: str | None = None,
        pending: bool | None = None,
        label: str | None = None,
    ) -> AsyncPager[Annotation, Paginated[Annotation]]:
        """List annotations. ``dataset_id`` applies that dataset's
        saved label predicate (a filter, not a membership). ``await``
        the returned :class:`AsyncPager` for the first page, or
        ``async for`` it to stream every annotation across pages."""

        async def fetch(cursor: str | None) -> Paginated[Annotation]:
            payload = await self._http.request(
                "GET",
                "/v1/annotations",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    include_total=include_total,
                    member_id=member_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    dataset_id=dataset_id,
                    pending=pending,
                    label=label,
                ),
            )
            return Paginated[Annotation].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        trace_id: str,
        span_id: str,
        member_id: str | None = None,
        labels: builtins.list[str] | None = None,
        comment: str | None = None,
        completed: bool | None = None,
    ) -> Annotation:
        """Annotate a span. ``member_id`` names the assignee — a
        foreign member requires a privileged caller and empty
        ``labels``/``comment``, and the row is forced pending.
        ``completed`` defaults to true server-side; pass ``False`` to
        create a pending review. Labels are normalized server-side
        (slugified, deduped, sorted)."""
        payload = await self._http.request(
            "POST",
            "/v1/annotations",
            json=_create_body(
                trace_id=trace_id,
                span_id=span_id,
                member_id=member_id,
                labels=labels,
                comment=comment,
                completed=completed,
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
        completed: bool | None = None,
    ) -> Annotation:
        """Update an annotation (owner-only server-side). ``labels``
        replaces wholesale and is normalized — ``[]`` clears, omit to
        leave alone. ``completed=True`` stamps ``completed_at``,
        ``False`` clears it back to pending."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/annotations/{annotation_id}",
            json=_update_body(
                labels=labels,
                comment=comment,
                completed=completed,
            ),
        )
        return Annotation.model_validate(payload)

    async def delete(self, annotation_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/annotations/{annotation_id}", expect="empty"
        )
