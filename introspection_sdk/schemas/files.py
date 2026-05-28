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


class FileUpdateRequest(_ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    metadata: dict[str, Any] | None = None


class FileCreateTextRequest(_ApiModel):
    name: str = Field(min_length=1, max_length=512)
    content: str
    mime_type: str = "text/markdown"
