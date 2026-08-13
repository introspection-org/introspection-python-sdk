"""Pydantic mirrors of DP `/v1/files` request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class FileType(StrEnum):
    UPLOAD = "upload"
    FILESYSTEM = "filesystem"
    OTHER = "other"


class File(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    name: str = Field(min_length=1, max_length=512)
    file_type: FileType = FileType.OTHER
    storage_path: str
    mime_type: str = "application/octet-stream"
    metadata: dict[str, Any] | None = None
    member_id: UUID | None = None
    size_bytes: int
    version: int = 1
    parent_id: UUID | None = None
    storage_version_id: str | None = None
    #: Coalesced caller identity that created this file.
    identity_key: str | None = None
    #: Task this file was created from (accounting only).
    task_id: UUID | None = None
    tags: list[str] = []
    """Grouping tags stamped on this file. Tags belong to the file rather
    than to a version, so they carry forward when a new version is written."""


class FileUpdateRequest(_ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    """Replaces the tag list wholesale (unlike ``metadata``, which is merged).
    ``None`` leaves tags untouched; ``[]`` clears them.

    A tag is an opaque, exact, case-sensitive string: ``key:value`` is a
    convention, not a grammar. Each tag is 1–128 characters with no whitespace
    or control characters; at most 64 tags. Duplicates collapse.

    Tags are access-bearing: a caller whose member tags intersect a file's tags
    can read and write it, so a tag shared with a member cohort hands them the
    file. Shared writers may not replace the tags themselves; that remains
    owner/privileged-only."""


class FileCreateTextRequest(_ApiModel):
    name: str = Field(min_length=1, max_length=512)
    content: str
    mime_type: str = "text/markdown"
