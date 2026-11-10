"""Wire models for append-only span annotations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AnnotationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str


class AnnotationComment(BaseModel):
    """One comment on an annotated span, as the export carries it."""

    model_config = ConfigDict(extra="allow")

    event_id: UUID
    comment: str
    #: The comment's author.
    member_id: UUID
    actor_member_id: UUID | None = None
    actor_member_type: str | None = None
    created_at: datetime


class AnnotationState(AnnotationTarget):
    """Current state folded from immutable annotation events.

    The list leaves ``comments`` as ``None``; the export sets it on every
    row, oldest first. For one span, the text is also on
    ``events.list("introspection.annotation", trace_id=..., span_id=...)``.
    """

    model_config = ConfigDict(extra="allow")

    conversation_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignee_member_ids: list[UUID] = Field(default_factory=list)
    #: Members whose comment completed a review. A data plane that predates
    #: the rename sends it as ``human_commenter_member_ids``.
    reviewer_member_ids: list[UUID] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "reviewer_member_ids", "human_commenter_member_ids"
        ),
    )
    comment_count: int = 0
    updated_at: datetime
    updated_by_member_id: UUID
    assignment_event_id: UUID | None = None
    comments: list[AnnotationComment] | None = None


class AnnotationFacet(BaseModel):
    """How many current annotations hold one value of one filter dimension
    (annotator, assignee, label, status or review_queue)."""

    model_config = ConfigDict(extra="allow")

    dimension: str
    value: str
    count: int
    #: Set on the ``label`` and ``review_queue`` buckets, which summarize a
    #: dataset.
    conversation_count: int | None = None
    comment_count: int | None = None
    reviewer_member_ids: list[UUID] | None = None
    updated_at: datetime | None = None


class AnnotationNavigation(BaseModel):
    """The review window around one annotated span: the rows before and
    after it in the filtered list, and its 1-based position there."""

    model_config = ConfigDict(extra="allow")

    previous: AnnotationState | None = None
    current: AnnotationState | None = None
    next: AnnotationState | None = None
    current_position: int | None = None
    total_count: int = 0


__all__ = [
    "AnnotationComment",
    "AnnotationFacet",
    "AnnotationNavigation",
    "AnnotationState",
    "AnnotationTarget",
]
