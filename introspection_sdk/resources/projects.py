"""``client.projects`` — CP namespace for ``/v1/projects``.

The org's projects, addressed by slug or id, and under each the runtime
peerings it offers or is granted (``projects.peerings``, read-only). Creating, updating and
deleting one needs ``projects:write`` / ``projects:delete``, which an
owner's or admin's session carries and no API key or service account does.
"""

from __future__ import annotations

from introspection_sdk._async.resources.projects import (
    AsyncProjectPeerings,
    AsyncProjects,
)
from introspection_sdk._sync.resources.projects import (
    ProjectPeerings,
    Projects,
)

__all__ = [
    "AsyncProjectPeerings",
    "AsyncProjects",
    "ProjectPeerings",
    "Projects",
]
