"""What a Person Server asks of its host: a `Store` for its state and a
`Directory` for who it speaks for. Neither names a database."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from introspection_aauth.person_server.models import (
    Approval,
    LogEntry,
    Mission,
)
from introspection_aauth.protocol.memory import compare_and_set


class Store(Protocol):
    """A Person Server's state, in logical operations, per tenant.

    `transaction()` yields a `Store` for one unit of work: every read and
    write through it commits together when the block ends, and anything raised
    inside it rolls them all back. It groups a decision that creates or spends
    a mission with the approval it decides, and a federated auth token with the
    spend it pays for.
    """

    async def select_binding(self, tenant: str, jkt: str) -> str | None:
        """The person an agent key is bound to."""
        ...

    async def insert_binding(self, tenant: str, jkt: str, person: str) -> str:
        """Bind a key to a person unless it is bound; whoever it is bound to."""
        ...

    async def select_mission(
        self, tenant: str, s256: str
    ) -> Mission | None: ...

    async def insert_mission(self, tenant: str, mission: Mission) -> bool:
        """Save an approved mission unless one with its hash exists."""
        ...

    async def update_spend(
        self,
        tenant: str,
        s256: str,
        amount: int | None,
        within_budget: bool,
        now: int,
    ) -> Mission | None:
        """Add `amount` to a live mission's spend, with `within_budget` only if
        it fits what is left. The mission, or None if it is not live or it does
        not fit. `amount` None checks only that it is live."""
        ...

    async def update_mission_log(
        self, tenant: str, s256: str, entry: LogEntry, now: int
    ) -> bool:
        """Append to a live mission's log; whether it was live."""
        ...

    async def update_mission_end(
        self, tenant: str, s256: str, at: int
    ) -> Mission | None:
        """Complete a live mission at `at`; it, or None if it was not live."""
        ...

    async def select_approval(
        self, tenant: str, approval_id: str
    ) -> Approval | None: ...

    async def insert_approval(self, tenant: str, approval: Approval) -> None:
        """Save a new approval."""
        ...

    async def transition_approval(
        self, tenant: str, current: Approval, changed: Approval
    ) -> bool:
        """Replace `current` with `changed` only if what is stored still has
        `current`'s status and version; whether it did. The stored `summary`
        is kept: only `update_approval_summary` writes it."""
        ...

    async def update_approval_summary(
        self, tenant: str, approval_id: str, summary: str
    ) -> bool:
        """Set an approval's summary, leaving its version as it is, so a
        decision or federation in flight is not made stale; whether it did."""
        ...

    def transaction(self) -> AbstractAsyncContextManager[Store]: ...


class Directory(Protocol):
    def person(self, login_hint: str, tenant: str) -> str | None:
        """The person a `login_hint` names in `tenant`, or None if this Person
        Server does not speak for them."""
        ...


class AnyoneDirectory:
    """Speaks for whoever the hint names: for samples and tests."""

    def person(self, login_hint: str, tenant: str) -> str | None:
        return login_hint or None


def _live(mission: Mission | None, now: int) -> Mission | None:
    if (
        mission is None
        or mission.completed_at is not None
        or mission.expires_at <= now
    ):
        return None
    return mission


class MemoryStore:
    """A `Store` in this process's memory."""

    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str], str] = {}
        self.missions: dict[tuple[str, str], Mission] = {}
        self.approvals: dict[tuple[str, str], Approval] = {}
        self._lock = asyncio.Lock()

    async def select_binding(self, tenant: str, jkt: str) -> str | None:
        return self.bindings.get((tenant, jkt))

    async def insert_binding(self, tenant: str, jkt: str, person: str) -> str:
        return self.bindings.setdefault((tenant, jkt), person)

    async def select_mission(self, tenant: str, s256: str) -> Mission | None:
        return self.missions.get((tenant, s256))

    async def insert_mission(self, tenant: str, mission: Mission) -> bool:
        if (tenant, mission.s256) in self.missions:
            return False
        self.missions[(tenant, mission.s256)] = mission
        return True

    async def update_spend(
        self,
        tenant: str,
        s256: str,
        amount: int | None,
        within_budget: bool,
        now: int,
    ) -> Mission | None:
        mission = _live(self.missions.get((tenant, s256)), now)
        if mission is None:
            return None
        if amount is None:
            return mission
        if within_budget and (
            mission.budget is None
            or mission.budget.amount - mission.spent < amount
        ):
            return None
        mission.spent += amount
        return mission

    async def update_mission_log(
        self, tenant: str, s256: str, entry: LogEntry, now: int
    ) -> bool:
        mission = _live(self.missions.get((tenant, s256)), now)
        if mission is not None:
            mission.log.append(entry)
        return mission is not None

    async def update_mission_end(
        self, tenant: str, s256: str, at: int
    ) -> Mission | None:
        mission = _live(self.missions.get((tenant, s256)), at)
        if mission is not None:
            mission.completed_at = at
        return mission

    async def select_approval(
        self, tenant: str, approval_id: str
    ) -> Approval | None:
        return self.approvals.get((tenant, approval_id))

    async def insert_approval(self, tenant: str, approval: Approval) -> None:
        self.approvals[(tenant, approval.id)] = approval

    async def transition_approval(
        self, tenant: str, current: Approval, changed: Approval
    ) -> bool:
        stored = self.approvals.get((tenant, current.id))
        if stored is not None:
            changed = changed.model_copy(update={"summary": stored.summary})
        return compare_and_set(
            self.approvals, (tenant, current.id), current, changed
        )

    async def update_approval_summary(
        self, tenant: str, approval_id: str, summary: str
    ) -> bool:
        stored = self.approvals.get((tenant, approval_id))
        if stored is None:
            return False
        self.approvals[(tenant, approval_id)] = stored.model_copy(
            update={"summary": summary}
        )
        return True

    def transaction(self) -> AbstractAsyncContextManager[Store]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[Store, None]:
        async with self._lock:
            saved = copy.deepcopy(
                (self.bindings, self.missions, self.approvals)
            )
            try:
                yield self
            except BaseException:
                self.bindings, self.missions, self.approvals = saved
                raise
