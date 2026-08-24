"""Pydantic mirrors of DP `/v1/annotations` request/response models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Annotation(_ApiModel):
    """A member's annotation on one OpenTelemetry span
    (`/v1/annotations`).

    ``completed_at`` is the review state: ``None`` means the
    annotation is a pending review.
    """

    id: UUID
    org_id: UUID
    project_id: UUID
    trace_id: str
    span_id: str
    labels: list[str]
    comment: str
    member_id: UUID
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AnnotationCreateRequest(_ApiModel):
    """Create a span annotation.

    ``member_id`` names the assignee — a foreign member requires a
    privileged caller and empty ``labels``/``comment``, and the server
    forces the row pending. ``labels`` are normalized server-side
    (slugified, deduped, sorted). ``completed`` defaults to true on
    the server; ``False`` creates a pending review."""

    trace_id: str
    span_id: str
    member_id: UUID | None = None
    labels: list[str] | None = None
    comment: str | None = None
    completed: bool | None = None


class AnnotationUpdateRequest(_ApiModel):
    """All-optional PATCH body (owner-only server-side). ``labels``
    replaces wholesale and is normalized; ``completed=True`` stamps
    ``completed_at``, ``False`` clears it back to pending."""

    labels: list[str] | None = None
    comment: str | None = None
    completed: bool | None = None
