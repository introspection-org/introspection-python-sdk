"""Project-level span annotations and managed label catalog."""

from __future__ import annotations

import builtins
import secrets
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.annotations import (
    AnnotationState,
    AnnotationTarget,
    ProjectLabel,
    ProjectLabelCreate,
    ProjectLabelUpdate,
)
from introspection_sdk.schemas.pagination import Paginated


def _uuid7() -> UUID:
    """Mint a UUIDv7 without depending on Python 3.14's ``uuid.uuid7``."""
    value = (
        (int(time.time() * 1000) & ((1 << 48) - 1)) << 80
    ) | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return UUID(int=value)


def _reviewer_emails(values: Sequence[str]) -> list[str]:
    emails = list(dict.fromkeys(value.strip().lower() for value in values))
    if not emails or any(not value for value in emails):
        raise ValidationError(
            "At least one non-empty reviewer email is required",
            status_code=422,
            code="invalid_annotation_reviewer_email",
        )
    if len(emails) > 64:
        raise ValidationError(
            "At most 64 reviewer emails are allowed",
            status_code=422,
            code="too_many_annotation_reviewers",
        )
    return emails


def _member_error(
    error: type[NotFoundError] | type[ConflictError],
    message: str,
    code: str,
    body: Any,
) -> Exception:
    return error(
        message,
        status_code=404 if error is NotFoundError else 409,
        code=code,
        body=body,
    )


class ProjectLabels:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[ProjectLabel, Paginated[ProjectLabel]]:
        def fetch(cursor: str | None) -> Paginated[ProjectLabel]:
            payload = self._http.request(
                "GET",
                "/v1/project-labels",
                params={"search": search, "limit": limit, "next": cursor},
            )
            return Paginated[ProjectLabel].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self, *, slug: str, color: str, description: str | None = None
    ) -> ProjectLabel:
        body = ProjectLabelCreate(
            slug=slug, color=color.lower(), description=description
        ).model_dump(mode="json", exclude_none=True)
        return ProjectLabel.model_validate(
            self._http.request("POST", "/v1/project-labels", json=body)
        )

    def get(self, slug: str) -> ProjectLabel:
        return ProjectLabel.model_validate(
            self._http.request(
                "GET", f"/v1/project-labels/{quote(slug, safe='')}"
            )
        )

    def update(self, slug: str, *, description: str | None) -> ProjectLabel:
        body = ProjectLabelUpdate(description=description).model_dump(
            mode="json"
        )
        return ProjectLabel.model_validate(
            self._http.request(
                "PATCH",
                f"/v1/project-labels/{quote(slug, safe='')}",
                json=body,
            )
        )


class Annotations:
    def __init__(self, cp_http: _HttpClient, dp_http: _HttpClient) -> None:
        self._cp_http = cp_http
        self._dp_http = dp_http

    def list(
        self,
        *,
        annotated_by_member_id: UUID | None = None,
        assignee_member_id: UUID | None = None,
        annotated_by_email: str | None = None,
        assigned_to_email: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        conversation_id: str | None = None,
        label: str | None = None,
        limit: int | None = None,
        next: str | None = None,
        include_total: bool | None = None,
    ) -> Pager[AnnotationState, Paginated[AnnotationState]]:
        if (
            annotated_by_member_id is not None
            and annotated_by_email is not None
        ):
            raise ValidationError(
                "Use annotated_by_member_id or annotated_by_email, not both",
                status_code=422,
                code="conflicting_annotation_annotator_filters",
            )
        if assignee_member_id is not None and assigned_to_email is not None:
            raise ValidationError(
                "Use assignee_member_id or assigned_to_email, not both",
                status_code=422,
                code="conflicting_annotation_assignee_filters",
            )
        if annotated_by_email is not None:
            annotated_by_member_id = self._resolve_reviewer_ids(
                [annotated_by_email]
            )[0]
        if assigned_to_email is not None:
            assignee_member_id = self._resolve_reviewer_ids(
                [assigned_to_email]
            )[0]

        def fetch(cursor: str | None) -> Paginated[AnnotationState]:
            payload = self._dp_http.request(
                "GET",
                "/v1/annotations",
                params={
                    "annotated_by_member_id": annotated_by_member_id,
                    "assignee_member_id": assignee_member_id,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "conversation_id": conversation_id,
                    "label": label,
                    "limit": limit,
                    "next": cursor,
                    "include_total": include_total,
                },
            )
            return Paginated[AnnotationState].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        trace_id: str,
        span_id: str,
        labels: Sequence[str] | None = None,
        comment: str | None = None,
        reviewer_emails: Sequence[str] | None = None,
        event_id: UUID | None = None,
    ) -> None:
        mutations = sum(
            value is not None for value in (labels, comment, reviewer_emails)
        )
        if mutations != 1:
            raise ValidationError(
                "Exactly one annotation mutation is required",
                status_code=422,
                code="invalid_annotation_mutation",
            )
        body: dict[str, Any] = AnnotationTarget(
            trace_id=trace_id, span_id=span_id
        ).model_dump()
        body["event_id"] = str(event_id or _uuid7())
        if labels is not None:
            body["labels"] = list(labels)
        elif comment is not None:
            body["comment"] = comment
        elif reviewer_emails is not None and len(reviewer_emails) == 0:
            body["assignee_member_ids"] = []
        else:
            body["assignee_member_ids"] = [
                str(value)
                for value in self._resolve_reviewer_ids(reviewer_emails or [])
            ]
        self._dp_http.request(
            "POST", "/v1/annotations", json=body, expect="empty"
        )

    def _resolve_reviewer_ids(
        self, values: Sequence[str]
    ) -> builtins.list[UUID]:
        requested = _reviewer_emails(values)
        matches: dict[str, list[UUID]] = {email: [] for email in requested}
        cursor: str | None = None
        while True:
            page = self._cp_http.request(
                "GET",
                "/v1/members",
                params={
                    "limit": 1000,
                    "member_type": "business",
                    "next": cursor,
                },
            )
            for member in page["records"]:
                email = (member.get("email") or "").strip().lower()
                if (
                    not member.get("is_deactivated", False)
                    and email in matches
                ):
                    matches[email].append(UUID(member["id"]))
            cursor = page.get("next") or None
            if cursor is None:
                break
        result: list[UUID] = []
        for email in requested:
            candidates = matches[email]
            if not candidates:
                raise _member_error(
                    NotFoundError,
                    f"No active domain expert found for '{email}'",
                    "annotation_reviewer_not_found",
                    {"email": email},
                )
            if len(candidates) > 1:
                raise _member_error(
                    ConflictError,
                    f"Multiple active domain experts found for '{email}'",
                    "annotation_reviewer_ambiguous",
                    {
                        "email": email,
                        "member_ids": [str(value) for value in candidates],
                    },
                )
            result.append(candidates[0])
        return result


class AsyncProjectLabels:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[ProjectLabel, Paginated[ProjectLabel]]:
        async def fetch(cursor: str | None) -> Paginated[ProjectLabel]:
            payload = await self._http.request(
                "GET",
                "/v1/project-labels",
                params={"search": search, "limit": limit, "next": cursor},
            )
            return Paginated[ProjectLabel].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self, *, slug: str, color: str, description: str | None = None
    ) -> ProjectLabel:
        body = ProjectLabelCreate(
            slug=slug, color=color.lower(), description=description
        ).model_dump(mode="json", exclude_none=True)
        return ProjectLabel.model_validate(
            await self._http.request("POST", "/v1/project-labels", json=body)
        )

    async def get(self, slug: str) -> ProjectLabel:
        return ProjectLabel.model_validate(
            await self._http.request(
                "GET", f"/v1/project-labels/{quote(slug, safe='')}"
            )
        )

    async def update(
        self, slug: str, *, description: str | None
    ) -> ProjectLabel:
        body = ProjectLabelUpdate(description=description).model_dump(
            mode="json"
        )
        return ProjectLabel.model_validate(
            await self._http.request(
                "PATCH",
                f"/v1/project-labels/{quote(slug, safe='')}",
                json=body,
            )
        )


class AsyncAnnotations:
    def __init__(
        self, cp_http: _AsyncHttpClient, dp_http: _AsyncHttpClient
    ) -> None:
        self._cp_http = cp_http
        self._dp_http = dp_http

    def list(
        self,
        *,
        annotated_by_member_id: UUID | None = None,
        assignee_member_id: UUID | None = None,
        annotated_by_email: str | None = None,
        assigned_to_email: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        conversation_id: str | None = None,
        label: str | None = None,
        limit: int | None = None,
        next: str | None = None,
        include_total: bool | None = None,
    ) -> AsyncPager[AnnotationState, Paginated[AnnotationState]]:
        if (
            annotated_by_member_id is not None
            and annotated_by_email is not None
        ):
            raise ValidationError(
                "Use annotated_by_member_id or annotated_by_email, not both",
                status_code=422,
                code="conflicting_annotation_annotator_filters",
            )
        if assignee_member_id is not None and assigned_to_email is not None:
            raise ValidationError(
                "Use assignee_member_id or assigned_to_email, not both",
                status_code=422,
                code="conflicting_annotation_assignee_filters",
            )
        resolved_annotator = annotated_by_member_id
        resolved_assignee = assignee_member_id
        filters_resolved = False

        async def fetch(cursor: str | None) -> Paginated[AnnotationState]:
            nonlocal resolved_annotator, resolved_assignee, filters_resolved
            if not filters_resolved:
                if annotated_by_email is not None:
                    resolved_annotator = (
                        await self._resolve_reviewer_ids([annotated_by_email])
                    )[0]
                if assigned_to_email is not None:
                    resolved_assignee = (
                        await self._resolve_reviewer_ids([assigned_to_email])
                    )[0]
                filters_resolved = True
            payload = await self._dp_http.request(
                "GET",
                "/v1/annotations",
                params={
                    "annotated_by_member_id": resolved_annotator,
                    "assignee_member_id": resolved_assignee,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "conversation_id": conversation_id,
                    "label": label,
                    "limit": limit,
                    "next": cursor,
                    "include_total": include_total,
                },
            )
            return Paginated[AnnotationState].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        trace_id: str,
        span_id: str,
        labels: Sequence[str] | None = None,
        comment: str | None = None,
        reviewer_emails: Sequence[str] | None = None,
        event_id: UUID | None = None,
    ) -> None:
        mutations = sum(
            value is not None for value in (labels, comment, reviewer_emails)
        )
        if mutations != 1:
            raise ValidationError(
                "Exactly one annotation mutation is required",
                status_code=422,
                code="invalid_annotation_mutation",
            )
        body: dict[str, Any] = AnnotationTarget(
            trace_id=trace_id, span_id=span_id
        ).model_dump()
        body["event_id"] = str(event_id or _uuid7())
        if labels is not None:
            body["labels"] = list(labels)
        elif comment is not None:
            body["comment"] = comment
        elif reviewer_emails is not None and len(reviewer_emails) == 0:
            body["assignee_member_ids"] = []
        else:
            body["assignee_member_ids"] = [
                str(value)
                for value in await self._resolve_reviewer_ids(
                    reviewer_emails or []
                )
            ]
        await self._dp_http.request(
            "POST", "/v1/annotations", json=body, expect="empty"
        )

    async def _resolve_reviewer_ids(
        self, values: Sequence[str]
    ) -> builtins.list[UUID]:
        requested = _reviewer_emails(values)
        matches: dict[str, list[UUID]] = {email: [] for email in requested}
        cursor: str | None = None
        while True:
            page = await self._cp_http.request(
                "GET",
                "/v1/members",
                params={
                    "limit": 1000,
                    "member_type": "business",
                    "next": cursor,
                },
            )
            for member in page["records"]:
                email = (member.get("email") or "").strip().lower()
                if (
                    not member.get("is_deactivated", False)
                    and email in matches
                ):
                    matches[email].append(UUID(member["id"]))
            cursor = page.get("next") or None
            if cursor is None:
                break
        result: list[UUID] = []
        for email in requested:
            candidates = matches[email]
            if not candidates:
                raise _member_error(
                    NotFoundError,
                    f"No active domain expert found for '{email}'",
                    "annotation_reviewer_not_found",
                    {"email": email},
                )
            if len(candidates) > 1:
                raise _member_error(
                    ConflictError,
                    f"Multiple active domain experts found for '{email}'",
                    "annotation_reviewer_ambiguous",
                    {
                        "email": email,
                        "member_ids": [str(value) for value in candidates],
                    },
                )
            result.append(candidates[0])
        return result


__all__ = [
    "Annotations",
    "AsyncAnnotations",
    "ProjectLabels",
    "AsyncProjectLabels",
]
