"""``client.members`` — CP namespace for ``/v1/members``.

Members are the organization's principals: ``business`` humans,
``agent`` members, and ``customer`` members minted from an asserted
identity (:class:`~introspection_sdk.schemas.runner.RunnerIdentity`).
``create`` invites a human by email, or (owner only) records a
``customer`` member by its ``external_user_id``; customer members are
also minted by identity assertion.

Reads need ``members:read``. ``update`` needs ``members:manage`` (owner),
as does seeding ``tags`` or ``policy_attributes`` on ``create``: a member
tag is access-bearing, and policy attributes decide what the member's agents
may do. ``metadata`` grants nothing.
"""

from __future__ import annotations

from introspection_sdk._async.resources.members import (
    AsyncMembers,
)
from introspection_sdk._sync.resources.members import (
    Members,
)

__all__ = [
    "AsyncMembers",
    "Members",
]
