"""Pydantic mirrors of CP `/v1/runtimes` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RuntimeLlmMode(StrEnum):
    """How a Runtime acquires LLM provider credentials at session create.

    - ``managed``: Introspection-managed keys (default; current behaviour).
    - ``byok``:    The project's Endpoint pool. Applicable LLM endpoints
                   are materialised into the session. Session create fails
                   with ``byok_no_endpoints`` if no applicable LLM endpoint
                   exists in the project.
    """

    MANAGED = "managed"
    BYOK = "byok"


RuntimeEnvironment = Literal["development", "staging", "production"]


class RuntimeKind(StrEnum):
    BYOR = "byor"
    BYOH = "byoh"


class RuntimeRecipeKind(StrEnum):
    PREVIEW = "preview"
    PRODUCTION = "production"


class RuntimeImageStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class RuntimeVersion(_ApiModel):
    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    kind: RuntimeKind = RuntimeKind.BYOR
    llm_mode: RuntimeLlmMode = RuntimeLlmMode.MANAGED
    config_json: dict[str, Any] = Field(default_factory=dict)
    project_id: UUID
    recipe_id: UUID
    runtime_group_id: UUID
    slug: str
    recipe_kind: RuntimeRecipeKind = RuntimeRecipeKind.PRODUCTION
    recipe_ref: str = "main"
    environments: list[RuntimeEnvironment] = Field(default_factory=list)
    image_tag: str | None = None
    image_status: RuntimeImageStatus = RuntimeImageStatus.PENDING
    image_built_at: datetime | None = None
    image_build_error: str | None = None
    image_size_bytes: int | None = None
    image_build_log_file_id: UUID | None = None
    created_by_member_id: UUID
    # When set, the runtime has been withdrawn and never resolves as the
    # active runtime for its environment; in-flight sticky runs keep using it.
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    # Per-environment git ref each lane tracks ({environment: 'main' | 'pr/N' |
    # <sha>}), projected from the runtime group.
    environment_ref: dict[RuntimeEnvironment, str] | None = None


__all__ = [
    "RuntimeEnvironment",
    "RuntimeImageStatus",
    "RuntimeKind",
    "RuntimeLlmMode",
    "RuntimeRecipeKind",
    "RuntimeVersion",
]
