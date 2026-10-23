"""``client.variables`` — CP namespace for ``/v1/variables``.

Environment variables a project's runtimes read, scoped like credentials.
"""

from __future__ import annotations

from introspection_sdk._async.resources.variables import (
    AsyncVariables,
)
from introspection_sdk._sync.resources.variables import (
    Variables,
)

__all__ = [
    "AsyncVariables",
    "Variables",
]
