"""What an Access Server calls back into its host: the policy that decides a
request, and a hook for each one left pending."""

from collections.abc import Awaitable
from typing import Protocol

from introspection_aauth.access_server.models import (
    AccessRequest,
    PendingAccess,
    Verdict,
)


class Policy(Protocol):
    """A resource's policy: its verdict on one request, now or awaited."""

    def __call__(
        self, request: AccessRequest, /
    ) -> Verdict | Awaitable[Verdict]: ...


class PendingHook(Protocol):
    """Told of each request the policy waits on."""

    def __call__(self, pending: PendingAccess, /) -> Awaitable[None]: ...
