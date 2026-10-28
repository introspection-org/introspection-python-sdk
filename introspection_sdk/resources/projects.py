"""``client.projects`` — CP namespace for ``/v1/projects``.

The org's projects, addressed by slug or id. Creating, updating and
deleting one needs ``projects:write`` / ``projects:delete``, which an
owner's or admin's session carries and no API key or service account does.
"""

from __future__ import annotations

from introspection_sdk._async.resources.projects import (
    AsyncProjects,
)
from introspection_sdk._sync.resources.projects import (
    Projects,
)

__all__ = [
    "AsyncProjects",
    "Projects",
]
