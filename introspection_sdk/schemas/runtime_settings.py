"""Pydantic mirrors of CP ``/v1/credentials`` and ``/v1/variables``.

Both are settings a project's runtimes read, scoped to the whole project, a
runtime group, one runtime and/or one lane. A credential's secret is
write-only: no read returns it, only whether one is set and a display hint.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from introspection_sdk.schemas._secrets import WireSecret
from introspection_sdk.schemas.lanes import Environment


class _Scope(BaseModel):
    """Where a setting applies. With neither ``runtime_id`` nor
    ``runtime_group_id`` it is project-wide; ``environment=None`` applies to
    every lane."""

    runtime_id: UUID | None = None
    runtime_group_id: UUID | None = None
    environment: Environment | None = None


class _Setting(_Scope):
    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str
    created_by_member_id: UUID


class _Request(_Scope):
    model_config = ConfigDict(extra="forbid")


class Credential(_Setting):
    """A runtime credential. The secret itself is never returned."""

    has_secret: bool = False
    secret_display: str | None = None
    secret_set_at: datetime | None = None


class CredentialCreateRequest(_Request):
    """Body of ``POST /v1/credentials``."""

    name: str
    secret: WireSecret


class CredentialUpdateRequest(_Request):
    """Body of ``PATCH /v1/credentials/{id}``. Set ``secret`` to rotate."""

    name: str | None = None
    secret: WireSecret | None = None


class VariableKind(StrEnum):
    VALUE = "value"
    """A plain value, returned on read."""
    CREDENTIAL = "credential"
    """A reference to a credential by name."""


class Variable(_Setting):
    """A runtime environment variable."""

    kind: VariableKind = VariableKind.VALUE
    value: str | None = None


class VariableCreateRequest(_Request):
    """Body of ``POST /v1/variables``."""

    name: str
    kind: VariableKind | None = None
    """Defaults to ``value`` server-side."""
    value: str | None = None


class VariableUpdateRequest(_Request):
    """Body of ``PATCH /v1/variables/{id}``."""

    name: str | None = None
    kind: VariableKind | None = None
    value: str | None = None


__all__ = [
    "Credential",
    "CredentialCreateRequest",
    "CredentialUpdateRequest",
    "Variable",
    "VariableCreateRequest",
    "VariableKind",
    "VariableUpdateRequest",
]
