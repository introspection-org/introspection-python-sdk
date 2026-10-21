"""``client.applications`` — CP namespace for ``/v1/applications``.

A project's OAuth clients, and under each the identity providers it brokers
(``applications.idps``), its client secrets (``applications.secrets``) and
its signing keys (``applications.keys``). Needs an org credential.
"""

from __future__ import annotations

from introspection_sdk._async.resources.applications import (
    AsyncApplicationIdps,
    AsyncApplicationKeys,
    AsyncApplications,
    AsyncApplicationSecrets,
)
from introspection_sdk._sync.resources.applications import (
    ApplicationIdps,
    ApplicationKeys,
    Applications,
    ApplicationSecrets,
)

__all__ = [
    "ApplicationIdps",
    "ApplicationKeys",
    "ApplicationSecrets",
    "Applications",
    "AsyncApplicationIdps",
    "AsyncApplicationKeys",
    "AsyncApplicationSecrets",
    "AsyncApplications",
]
