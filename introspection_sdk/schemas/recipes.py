"""Pydantic mirrors of CP `/v1/recipes` response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RecipeValidationDiagnostic(ApiModel):
    """One finding of a recipe check."""

    code: str
    severity: str = "error"
    path: str
    """The file the diagnostic is about."""
    span: dict[str, Any] | None = None
    message: str
    help: str | None = None


class RecipeValidation(ApiModel):
    """The recipe check of a recipe's commit."""

    status: str = "pending"
    """``pending``, ``valid``, ``invalid`` or ``failed`` (the check could
    not run; ``error_message`` says why)."""
    validator_name: str | None = None
    validator_version: str | None = None
    checked_at: datetime | None = None
    error_message: str | None = None
    diagnostics: list[RecipeValidationDiagnostic] = Field(default_factory=list)


class Recipe(ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    repository_id: UUID
    name: str
    slug: str
    git_ref: str
    git_commit_sha: str
    git_commit_subject: str | None = None
    sub_path: str | None = None
    description: str | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    """MCP servers the recipe declares (``id``, ``required``, ``tools``)."""
    policies: dict[str, Any] | None = None
    """The recipe's Cedar policies (``schema``, ``policies``, ``routes``)."""
    agents: list[str] | None = None
    """The agents this version defines, from ``agents/<name>.yaml``, the
    default first. ``None`` until checked."""
    issue_providers: list[str] | None = None
    validation: RecipeValidation | None = None
    created_by_member_id: UUID
    created_at: datetime
    updated_at: datetime


class RecipeCreate(BaseModel):
    """Body of ``POST /v1/recipes``: a recipe pinned to one commit of a
    repository."""

    project: str
    name: str
    repository_id: UUID | None = None
    git_ref: str | None = None
    git_commit_sha: str | None = None
    git_commit_subject: str | None = None
    sub_path: str | None = None
    slug: str | None = None
    description: str | None = None


class RecipeUpdate(BaseModel):
    """Body of ``PATCH /v1/recipes/{id}``; an unset field is left as is."""

    name: str | None = None
    description: str | None = None


__all__ = [
    "Recipe",
    "RecipeCreate",
    "RecipeUpdate",
    "RecipeValidation",
    "RecipeValidationDiagnostic",
]
