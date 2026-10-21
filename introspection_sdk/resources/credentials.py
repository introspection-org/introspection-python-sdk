"""``client.credentials`` — CP namespace for ``/v1/credentials``.

Secrets a project's runtimes read. The secret is write-only: no read returns
it. Not to be confused with the ``credentials=`` constructor argument, which
authenticates the client itself.
"""

from __future__ import annotations

from introspection_sdk._async.resources.credentials import (
    AsyncCredentials,
)
from introspection_sdk._sync.resources.credentials import (
    Credentials,
)

__all__ = [
    "AsyncCredentials",
    "Credentials",
]
