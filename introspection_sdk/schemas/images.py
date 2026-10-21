"""Pydantic mirrors of DP ``/v1/images`` request/response models.

An image lands in the plane's registry and is what an eval task's compose
services run as. It is built from a context archive uploaded through the
Files API, or mirrored from an upstream reference pinned by digest. A create
is idempotent on content, and ``status`` is the only progress report.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ImageKind(StrEnum):
    """What produced an image."""

    RUNTIME = "runtime"
    """A Recipe bake."""
    SERVICE = "service"
    """A caller's ``POST /v1/images``."""


class ImageStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EVICTED = "evicted"


class ImageScanStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FINDINGS = "findings"
    FAILED = "failed"
    SKIPPED = "skipped"


class ImageSourceKind(StrEnum):
    CONTEXT = "context"
    MIRROR = "mirror"
    BAKE = "bake"


class Image(BaseModel):
    """An image in the plane's registry."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    kind: ImageKind
    name: str
    content_id: str
    """What a create dedupes on: a repeat create of the same content returns
    this row."""
    source_kind: ImageSourceKind
    source: dict[str, Any]
    build_platform: str
    service: str | None = None
    repository_id: UUID | None = None
    git_sha: str | None = None
    git_ref: str | None = None
    path: str = ""
    runtime_id: UUID | None = None
    task_id: UUID | None = None
    trigger: str | None = None
    base_image_digest: str | None = None
    base_image_tag: str | None = None
    external_artifacts: dict[str, str] | None = None
    external_image_name: str | None = None
    status: ImageStatus
    image_ref: str | None = None
    image_digest: str | None = None
    size_bytes: int | None = None
    warnings: list[str] = []
    error: str | None = None
    scan_status: ImageScanStatus | None = None
    scan_started_at: datetime | None = None
    scanned_at: datetime | None = None
    scan_db_built_at: datetime | None = None
    scan_summary: dict[str, Any] | None = None
    scan_report_file_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_used_at: datetime | None = None
    evicted_at: datetime | None = None
    retired_at: datetime | None = None

    @property
    def pull_reference(self) -> str | None:
        """The digest-pinned reference a compose service names, once
        ready."""
        if self.image_ref and self.image_digest:
            return f"{self.image_ref}@{self.image_digest}"
        return None


class ContextImageSource(BaseModel):
    """Build from a Dockerfile inside a ``.tar.gz`` uploaded through the
    Files API."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["context"] = "context"
    file_id: UUID
    dockerfile: str | None = None
    """A path inside the archive; defaults to ``Dockerfile``."""
    platform: str | None = None
    """``linux/amd64`` or ``linux/arm64``; defaults to the plane's sandbox
    platform."""


class MirrorImageSource(BaseModel):
    """Copy an upstream image, pinned by digest (``...@sha256:...``), into the
    plane's registry."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["mirror"] = "mirror"
    reference: str


ImageSource = Annotated[
    ContextImageSource | MirrorImageSource, Field(discriminator="kind")
]
"""Where an image's bytes come from, tagged by ``kind``."""


class ImageProvenance(BaseModel):
    """Where a Recipe publish built an image from, and the compose service it
    runs as."""

    model_config = ConfigDict(extra="forbid")

    service: str
    """The compose service name, a DNS label."""
    repository_id: UUID | None = None
    git_sha: str | None = None
    path: str | None = None


class ImageCreateRequest(BaseModel):
    """Body of ``POST /v1/images``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    """Lowercase path segments, e.g. ``hello-mcp/mcp-server``."""
    source: ImageSource
    provenance: ImageProvenance | None = None
    scan: bool | None = None
    """Ask for (``True``) or opt out of (``False``) a vulnerability scan
    within what the plane's policy allows; ``None`` takes the policy."""


IMAGE_SOURCE_ADAPTER: TypeAdapter[ImageSource] = TypeAdapter(ImageSource)

__all__ = [
    "IMAGE_SOURCE_ADAPTER",
    "ContextImageSource",
    "Image",
    "ImageCreateRequest",
    "ImageKind",
    "ImageProvenance",
    "ImageScanStatus",
    "ImageSource",
    "ImageSourceKind",
    "ImageStatus",
    "MirrorImageSource",
]
