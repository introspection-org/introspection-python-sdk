"""``client.runtimes`` — read, resolve, and run runtimes.

``client.runtimes`` is the :class:`Runtimes` instance; calling
``client.runtimes(runtime)`` returns a :class:`RuntimeHandle`
which exposes ``.run()``. A slug goes straight to
``POST /v1/runtimes/{slug}/run``, which resolves it in the caller's project,
so opening a runner needs no list call. A UUID selector is a runtime group
id and is resolved on the caller's project on every use. Neither is cached,
so a version withdrawn after the handle was built cannot strand it.
Concrete runtime row IDs are used only by explicit ``*_id`` methods.
"""

from __future__ import annotations

from introspection_sdk._async.resources.runtimes import (
    AsyncRuntimes,
)
from introspection_sdk._sync.resources.runtimes import (
    Runtimes,
)
from introspection_sdk.resources._runtimes_common import (
    AsyncRuntimeHandle,
    RuntimeHandle,
)

__all__ = [
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "RuntimeHandle",
    "Runtimes",
]
