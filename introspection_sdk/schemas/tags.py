"""Wire models for the project tag catalogue.

A catalogue row names a tag people pick from; it grants nothing. The two kinds
are separate catalogues with separate scopes, and their fields differ — an
``access`` tag is an opaque value with no colour, an ``annotation`` tag is a
slug that must have one. ``TagCreate`` is a discriminated union on ``kind`` so
that rule is unrepresentable rather than validated.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

TagName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class TagKind(StrEnum):
    """Which catalogue a tag belongs to.

    ``access`` tags are the values tag shares and member tags carry;
    ``annotation`` tags are the annotation labels.
    """

    ACCESS = "access"
    ANNOTATION = "annotation"


class Tag(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: TagKind
    name: str
    #: Set on an ``annotation`` tag; never on an ``access`` tag.
    color: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class AccessTagCreate(BaseModel):
    """An access tag's name is opaque and kept verbatim, so it may contain ``/``."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[TagKind.ACCESS] = TagKind.ACCESS
    name: TagName
    description: str | None = Field(default=None, max_length=2000)


class AnnotationTagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[TagKind.ANNOTATION] = TagKind.ANNOTATION
    #: Slugified by the API, so a display name is accepted here.
    name: TagName
    color: HexColor
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("color")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


#: A tag to add. The kind picks the member, so an access tag has no colour to
#: set and an annotation tag cannot omit one.
TagCreate = Annotated[
    AccessTagCreate | AnnotationTagCreate, Field(discriminator="kind")
]


class TagUpdate(BaseModel):
    """A field left unset is left as it is; ``description=None`` clears it.

    The API distinguishes an omitted field from a null, so this is dumped with
    ``exclude_unset=True`` rather than ``exclude_none=True``.
    """

    model_config = ConfigDict(extra="forbid")

    color: HexColor | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("color")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return value.lower() if value else value


__all__ = [
    "AccessTagCreate",
    "AnnotationTagCreate",
    "HexColor",
    "Tag",
    "TagCreate",
    "TagKind",
    "TagName",
    "TagUpdate",
]
