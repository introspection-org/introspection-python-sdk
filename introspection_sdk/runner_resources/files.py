"""`runner.files.*` namespace: list / upload / download / versions.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.files import (
    AsyncFiles,
    AsyncFileVersions,
    FileLike,
)
from introspection_sdk._async.runner_resources.files import (
    _materialise_upload as _materialise_upload,
)
from introspection_sdk._sync.runner_resources.files import (
    Files,
    FileVersions,
)

__all__ = [
    "AsyncFileVersions",
    "AsyncFiles",
    "FileLike",
    "FileVersions",
    "Files",
]
