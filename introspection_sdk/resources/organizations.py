"""``client.organizations`` — CP ``/v1/organizations/me``: the
credential's own organization.
"""

from __future__ import annotations

from introspection_sdk._async.resources.organizations import (
    AsyncOrganizations,
)
from introspection_sdk._sync.resources.organizations import Organizations

__all__ = ["AsyncOrganizations", "Organizations"]
