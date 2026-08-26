"""Wire models for append-only span annotations and managed labels."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

LabelSlug = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


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


class ProjectLabel(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    color: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectLabelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: LabelSlug
    color: HexColor
    description: str | None = Field(default=None, max_length=2000)


class ProjectLabelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(max_length=2000)


__all__ = [
    "AnnotationState",
    "AnnotationTarget",
    "ProjectLabel",
    "ProjectLabelCreate",
    "ProjectLabelUpdate",
]
