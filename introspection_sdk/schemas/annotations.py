"""Wire models for append-only span annotations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

AnnotationInclude = Literal["comments"]
"""Optional expansions of a listed row, passed as a repeated ``include``
query param: ``comments`` sets each row's ``comments``."""


class AnnotationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str


class AnnotationComment(BaseModel):
    """One comment on an annotated span, as ``include=comments`` carries it."""

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

    ``comments`` is ``None`` unless the list was read with
    ``include=["comments"]``, which sets it on every row, oldest first.
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
    "AnnotationInclude",
    "AnnotationNavigation",
    "AnnotationState",
    "AnnotationTarget",
]
