"""What an Access Server keeps: the requests its policy is waiting on."""

from typing import Protocol

from ..protocol.memory import compare_and_set
from .models import PendingAccess


class Store(Protocol):
    async def select_pending(
        self, pending_id: str
    ) -> PendingAccess | None: ...

    async def insert_pending(self, pending: PendingAccess) -> None: ...

    async def transition_pending(
        self, current: PendingAccess, changed: PendingAccess
    ) -> bool:
        """Replace `current` with `changed` only if what is stored still has
        `current`'s status and version; whether it did."""
        ...


class MemoryStore:
    """A `Store` in this process's memory."""

    def __init__(self) -> None:
        self.requests: dict[str, PendingAccess] = {}

    async def select_pending(self, pending_id: str) -> PendingAccess | None:
        return self.requests.get(pending_id)

    async def insert_pending(self, pending: PendingAccess) -> None:
        self.requests[pending.id] = pending

    async def transition_pending(
        self, current: PendingAccess, changed: PendingAccess
    ) -> bool:
        return compare_and_set(self.requests, current.id, current, changed)
