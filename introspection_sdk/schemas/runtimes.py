"""Pydantic mirrors of CP `/v1/runtimes` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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


class Runtime(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    recipe_id: UUID | None = None
    is_active: bool = False
    description: str | None = None
    metadata: dict[str, Any] | None = None
    llm_mode: RuntimeLlmMode = RuntimeLlmMode.MANAGED
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuntimeCreate(_ApiModel):
    project_id: UUID
    name: str
    recipe_id: UUID | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None
    llm_mode: RuntimeLlmMode = RuntimeLlmMode.MANAGED


class RuntimeUpdate(_ApiModel):
    name: str | None = None
    recipe_id: UUID | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None
    llm_mode: RuntimeLlmMode | None = None


__all__ = ["Runtime", "RuntimeCreate", "RuntimeLlmMode", "RuntimeUpdate"]
