"""``remotes`` — DP ``/v1/remotes``: the WebSocket ``introspection dev``
dials out on to attach a local remote."""

from __future__ import annotations

from introspection_sdk._async.runner_resources.remotes import (
    REMOTES_CONNECT_PATH,
    AsyncRemotes,
)
from introspection_sdk._sync.runner_resources.remotes import Remotes

__all__ = ["REMOTES_CONNECT_PATH", "AsyncRemotes", "Remotes"]
