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


class RuntimeResolutionMode(StrEnum):
    """How a runtime group resolves which runtime serves a run.

    - ``sticky``: a run pins the runtime that was active when it started and
      keeps using it for the whole conversation, even after a newer runtime
      is promoted. The production default.
    - ``latest``: every run (including restarts of an existing task) resolves
      the runtime currently active for the environment. The default for
      non-production environments.

    A per-run override on the run request beats the group's setting; a yanked
    runtime is never resolved under either mode.
    """

    STICKY = "sticky"
    LATEST = "latest"


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


class RuntimeCreate(_ApiModel):
    project_id: UUID
    name: str
    slug: str | None = None
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


__all__ = [
    "Runtime",
    "RuntimeCreate",
    "RuntimeLlmMode",
    "RuntimeResolutionMode",
    "RuntimeUpdate",
]
