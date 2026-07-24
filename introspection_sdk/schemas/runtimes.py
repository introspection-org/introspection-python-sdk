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
    slug: str
    recipe_id: UUID | None = None
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


__all__ = [
    "Runtime",
    "RuntimeLlmMode",
]
