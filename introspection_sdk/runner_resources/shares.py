"""`runner.shares.*` namespace: sharing grants for files, issues and conversations.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets the
runner's DP endpoint with its short-lived JWT. ``create`` / ``list`` / ``get`` /
``update`` / ``delete`` manage grants. Shares are ambient: a shared resource
appears in the grantee's ordinary reads, and a grant's ``url`` is the plain
resource URL. To share with a cohort, create a share with ``granted_tag``. To
fork a new task from a shared conversation, pass ``fork_share_id`` to
``runner.tasks.create(...)``; the API refuses one whose share has
``visible_from`` set.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.shares import (
    AsyncShares,
)
from introspection_sdk._sync.runner_resources.shares import (
    Shares,
)

__all__ = [
    "AsyncShares",
    "Shares",
]
