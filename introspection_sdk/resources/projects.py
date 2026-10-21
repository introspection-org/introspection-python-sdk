"""``client.projects`` — CP namespace for ``/v1/projects``.

The org's projects, read by slug or id. Read-only here: writing a project
needs ``projects:write``, which no API key, service account or CLI login
carries.
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
