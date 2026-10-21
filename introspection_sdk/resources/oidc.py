"""``client.oidc`` — CP ``/v1/oidc/me``: who the client's credential
signs in as.
"""

from __future__ import annotations

from introspection_sdk._async.resources.oidc import (
    AsyncOidc,
)
from introspection_sdk._sync.resources.oidc import (
    Oidc,
)

__all__ = [
    "AsyncOidc",
    "Oidc",
]
