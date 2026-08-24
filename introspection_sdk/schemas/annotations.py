"""Pydantic mirrors of DP `/v1/annotations` request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
)


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AnnotationKind(StrEnum):
    """Expert-distillation annotation families."""

    REVIEW = "review"
    MARK = "mark"
    MEMBERSHIP = "membership"


class AnnotationActorType(StrEnum):
    """Who acted on behalf of the annotation's member."""

    AGENT = "agent"
    DEV = "dev"
    IMPERSONATION = "impersonation"


class AnnotationSelection(_ApiModel):
    """A span of conversation content an annotation anchors to.

    Every locator field is optional, but a selection always carries the
    ``quoted_text`` it points at.
    """

    message_id: str | None = None
    span_id: str | None = None
    part_index: int | None = None
    start: int | None = None
    end: int | None = None
    quoted_text: str


class Annotation(_ApiModel):
    """An open-coding annotation over a conversation (`/v1/annotations`)."""

    id: UUID
    org_id: UUID
    project_id: UUID
    conversation_id: str
    kind: AnnotationKind
    parent_id: UUID | None = None
    selection: AnnotationSelection | None = None
    labels: list[str]
    comment: str
    member_id: UUID
    actor_member_id: UUID | None = None
    actor_type: AnnotationActorType | None = None
    share_id: UUID | None = None
    dataset_id: UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AnnotationCreateRequest(_ApiModel):
    """Create an annotation. ``member_id`` names the review assignee
    (privileged-only when foreign); omit it to annotate as the caller.
    Pending-review/membership creates are idempotent server-side — a
    repeat create returns the existing row."""

    # A conversation id is not a uuid, so the wire type is a plain
    # string — coercing here lets a UUID be fed back without a
    # validation error.
    conversation_id: Annotated[str, BeforeValidator(str)]
    kind: AnnotationKind
    member_id: UUID | None = None
    parent_id: UUID | None = None
    selection: AnnotationSelection | None = None
    labels: list[str] | None = None
    comment: str | None = None
    dataset_id: UUID | None = None


class AnnotationUpdateRequest(_ApiModel):
    """All-optional PATCH body. ``labels`` replaces wholesale (``[]``
    clears, omit to leave); ``completed=True`` stamps ``completed_at``,
    ``False`` clears it."""

    labels: list[str] | None = None
    comment: str | None = None
    selection: AnnotationSelection | None = None
    completed: bool | None = None
