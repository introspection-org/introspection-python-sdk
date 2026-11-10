"""Wire models for append-only span annotations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnotationTarget(BaseModel):
    """The span an annotation write names (a request body)."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str


class AnnotationState(AnnotationTarget):
    """Current state folded from immutable annotation events.

    A response model: it overrides the ``forbid`` it would inherit from
    :class:`AnnotationTarget`, so a field the API adds is ignored."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignee_member_ids: list[UUID] = Field(default_factory=list)
    annotator_member_ids: list[UUID] = Field(default_factory=list)
    has_comment: bool = False
    comment_count: int = 0
    latest_comment: str | None = None
    latest_comment_member_id: UUID | None = None
    updated_at: datetime
    updated_by_member_id: UUID
    assignment_event_id: UUID | None = None


class AnnotationFacet(BaseModel):
    """How many current annotations hold one value of one filter dimension
    (annotator, assignee, label or status)."""

    dimension: str
    value: str
    count: int


class AnnotationNavigation(BaseModel):
    """The review window around one annotated span: the rows before and
    after it in the filtered list, and its 1-based position there."""

    previous: AnnotationState | None = None
    current: AnnotationState | None = None
    next: AnnotationState | None = None
    current_position: int | None = None
    total_count: int = 0


__all__ = [
    "AnnotationFacet",
    "AnnotationNavigation",
    "AnnotationState",
    "AnnotationTarget",
]
