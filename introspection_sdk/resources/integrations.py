"""``client.integrations`` — CP namespace for ``/v1/integrations``.

The org's own provider installs (a GitHub App installation, a Slack
workspace). Org-wide, so no project selector.
"""

from __future__ import annotations

from introspection_sdk._async.resources.integrations import (
    AsyncIntegrations,
)
from introspection_sdk._sync.resources.integrations import (
    Integrations,
)

__all__ = [
    "AsyncIntegrations",
    "Integrations",
]
