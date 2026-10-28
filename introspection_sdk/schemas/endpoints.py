"""Pydantic mirrors of CP ``/v1/endpoints``: the upstream hosts a project's
runtimes reach, an MCP server's binding among them.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EndpointKind(StrEnum):
    """An endpoint's role.

    - ``llm``: a model provider; counts toward a BYOK runtime's pool.
    - ``api``: a plain upstream HTTP API.
    - ``mcp``: an MCP server's binding (``metadata.mcp_server_id``).
    """

    LLM = "llm"
    API = "api"
    MCP = "mcp"


class EndpointMetadata(BaseModel):
    """An endpoint's non-secret metadata; the MCP fields are set only for
    ``kind="mcp"``."""

    model_config = ConfigDict(extra="allow")

    mcp_server_id: str | None = None
    connector_id: UUID | None = None
    """The connector whose stored connection authenticates the MCP server."""
    provider_app: str | None = None
    extra_hosts: list[str] = Field(default_factory=list)
    auth_audience: str | None = None


class Endpoint(BaseModel):
    """An upstream host a project's runtimes reach, scoped to a runtime
    group, a runtime and an environment where those are set (``None``
    means every one)."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    host: str
    base_url: str | None = None
    kind: EndpointKind | str = EndpointKind.LLM
    metadata: EndpointMetadata = Field(default_factory=EndpointMetadata)
    assertion_claims: dict[str, Any] | None = None
    runtime_id: UUID | None = None
    runtime_group_id: UUID | None = None
    environment: str | None = None
    verify_path: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    """Configured header values, credential references left unresolved."""
    header_names: list[str] = Field(default_factory=list)
    credential_refs: list[str] = Field(default_factory=list)
    """The credential names header values reference as ``${NAME}``."""
    last_verified_at: datetime | None = None
    authorized_application_id: UUID | None = None
    created_by_member_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EndpointUpdate(BaseModel):
    """Body of ``PATCH /v1/endpoints/{id}``; an unset field is left as is."""

    name: str | None = None
    host: str | None = None
    base_url: str | None = None
    headers: dict[str, str] | None = None
    kind: EndpointKind | None = None
    metadata: EndpointMetadata | None = None
    assertion_claims: dict[str, Any] | None = None
    runtime_id: UUID | None = None
    runtime_group_id: UUID | None = None
    environment: str | None = None
    verify_path: str | None = None
    authorized_application_id: UUID | None = None


__all__ = ["Endpoint", "EndpointKind", "EndpointMetadata", "EndpointUpdate"]
