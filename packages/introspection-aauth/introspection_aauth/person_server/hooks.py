"""What a Person Server calls back into its host: hooks for the approvals it
raises, and the waits and exchanges of a federation a host may journal."""

from collections.abc import Awaitable
from typing import Protocol

from introspection_aauth.person_server.models import (
    Approval,
    Outcome,
)


class Hook(Protocol):
    """Told of an approval in `tenant`: one a person must decide, or one
    its resource's Access Server must."""

    def __call__(
        self, tenant: str, approval: Approval, /
    ) -> Awaitable[None]: ...


class Sleep(Protocol):
    """Waits `seconds`; a durable host passes its own."""

    def __call__(self, seconds: float, /) -> Awaitable[None]: ...


class Exchange(Protocol):
    """One exchange with the Access Server."""

    def __call__(self) -> Awaitable[Outcome]: ...
