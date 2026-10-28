"""Pydantic mirror of the CP ``/v1/projects/{project}/peerings`` read model.

Unknown fields are tolerated via ``extra="allow"`` so CP additions don't
break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RuntimePeering(BaseModel):
    """A source project offering one of its runtime groups' configuration to
    other projects.

    ``org_id`` / ``project_id`` / ``runtime_group_id`` are the source, which
    owns the peering. The ``granted_*`` fields name who it admits; they are
    ANDed, and ``None`` matches anything.
    """

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    project_id: UUID
    runtime_group_id: UUID
    created_at: datetime
    updated_at: datetime
    granted_org_id: UUID | None = None
    granted_project_id: UUID | None = None
    """Narrows the grant to one project of ``granted_org_id``."""
    granted_deployment_id: UUID | None = None
    expires_at: datetime | None = None
    """When the peering stops admitting anyone."""
    created_by_member_id: UUID | None = None


__all__ = ["RuntimePeering"]
