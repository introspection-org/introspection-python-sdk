"""Wire models for append-only span annotations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnotationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str


class AnnotationState(AnnotationTarget):
    """Current state folded from immutable annotation events."""

    model_config = ConfigDict(extra="allow")

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


__all__ = [
    "AnnotationState",
    "AnnotationTarget",
]
