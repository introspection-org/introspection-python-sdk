"""Pydantic mirrors of CP `/v1/runtimes` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
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


class RuntimeGroupType(StrEnum):
    """Who a runtime group belongs to.

    - ``managed``: a first-party runtime Introspection owns.
    - ``custom``:  any other runtime (default).
    """

    MANAGED = "managed"
    CUSTOM = "custom"


class RuntimeInclude(StrEnum):
    """A read-time projection :meth:`Runtimes.get` can ask for.

    - ``mcp_requirements``: every MCP server the recipe declares, with the
      connector, connection and endpoint that satisfy it per environment.
    """

    MCP_REQUIREMENTS = "mcp_requirements"


class Runtime(ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    slug: str
    recipe_id: UUID | None = None
    # The group every version of this runtime shares; its slug or this id
    # selects the group's live version.
    runtime_group_id: UUID | None = None
    created_by_member_id: UUID | None = None
    # `byor`, `byoh` or `platform`; a string so a kind the API adds reads.
    kind: str = "byor"
    config_json: dict[str, Any] | None = None
    # `preview` or `production`, and the ref the recipe is read at.
    recipe_kind: str = "production"
    recipe_ref: str = "main"
    # The environments this version serves.
    environments: list[str] = Field(default_factory=list)
    # The image bake: `pending`, `queued`, `building`, `ready`, `failed` or
    # `skipped`, its error, and what the build produced (`image_tag`,
    # `built_at`, `size_bytes`, ...).
    image_build_status: str = "pending"
    image_build_error_message: str | None = None
    image_build_metadata: dict[str, Any] | None = None
    # Only with `include=[RuntimeInclude.MCP_REQUIREMENTS]`: each declared
    # MCP server and what satisfies it per environment.
    mcp_requirements: list[dict[str, Any]] | None = None
    is_active: bool = False
    description: str | None = None
    metadata: dict[str, Any] | None = None
    llm_mode: RuntimeLlmMode = RuntimeLlmMode.MANAGED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # When set, the runtime has been withdrawn and never resolves as the
    # active runtime for its environment; in-flight sticky runs keep using it.
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    # Per-environment git ref each lane tracks ({environment: 'main' | 'pr/N' |
    # <sha>}), projected from the runtime group.
    environment_ref: dict[str, str] | None = None
    # Projected from the runtime group: who owns it and the template it was
    # created from.
    runtime_group_type: RuntimeGroupType = RuntimeGroupType.CUSTOM
    template_ref: str | None = None
    # For an image version: the recipe commit its image carries, that
    # commit's subject line, and the recipe's GitHub repository (owner/name).
    image_revision: str | None = None
    image_commit_subject: str | None = None
    image_repository: str | None = None


class RuntimeCreate(BaseModel):
    """Body of ``POST /v1/runtimes``: a new version of the group ``slug``
    names (or a new group), pinned to ``recipe_id``."""

    project: str
    name: str
    recipe_id: UUID | None = None
    slug: str | None = None
    description: str | None = None
    kind: str | None = None
    llm_mode: RuntimeLlmMode | None = None
    config_json: dict[str, Any] | None = None
    template_ref: str | None = None
    bootstrap: bool | None = None


class RuntimeUpdate(BaseModel):
    """Body of ``PATCH /v1/runtimes/{id}``; an unset field is left as is."""

    name: str | None = None
    description: str | None = None
    llm_mode: RuntimeLlmMode | None = None
    config_json: dict[str, Any] | None = None
    environment: str | None = None
    yanked: bool | None = None
    yanked_reason: str | None = None
    environment_ref: dict[str, str] | None = None


__all__ = [
    "Runtime",
    "RuntimeCreate",
    "RuntimeGroupType",
    "RuntimeInclude",
    "RuntimeLlmMode",
    "RuntimeUpdate",
]
