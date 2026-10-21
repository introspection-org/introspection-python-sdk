"""``images`` — DP namespace for ``/v1/images``, on the client and a Runner.

What an eval task's compose services run as: built from a context archive
uploaded through the Files API, or mirrored from a digest-pinned upstream
reference, into the plane's registry.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.images import AsyncImages
from introspection_sdk._sync.runner_resources.images import Images

__all__ = ["AsyncImages", "Images"]
