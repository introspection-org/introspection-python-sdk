"""Re-exported by :mod:`introspection_sdk.runner_resources.aauth`."""

from __future__ import annotations

import builtins
import logging
from uuid import UUID

from introspection_sdk._async.resources._crud import _AsyncResource
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.aauth import (
    Approval,
    ApprovalDecision,
    ApprovalKind,
    ApprovalStatus,
    ApproverIdentity,
    Budget,
    Mission,
)
from introspection_sdk.schemas.pagination import Paginated

logger = logging.getLogger(__name__)


def _id(value: UUID | str | None) -> str | None:
    return str(value) if value else None


class AsyncMissions(_AsyncResource):
    """DP ``/v1/aauth/missions``: the missions the project's people approved
    agents to carry out."""

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Mission, Paginated[Mission]]:
        """List missions, newest first; ``member_id`` keeps one person's.
        The returned pager streams every mission; ``.page()`` reads the
        first page only."""
        logger.debug(
            "aauth missions listed", extra={"member_id": _id(member_id)}
        )
        return self._paginate(
            "/v1/aauth/missions",
            Paginated[Mission],
            {"member_id": _id(member_id), "limit": limit, "next": next},
        )

    async def get(self, mission_id: UUID | str) -> Mission:
        """Read one mission; an unknown id is a ``NotFoundError``."""
        return await self._call(
            "GET", f"/v1/aauth/missions/{mission_id}", Mission
        )


class AsyncApprovals(_AsyncResource):
    """DP ``/v1/aauth/approvals``: the decisions agents ask the project's
    people to make."""

    def list(
        self,
        *,
        status: builtins.list[ApprovalStatus | str] | None = None,
        kind: ApprovalKind | str | None = None,
        member_id: UUID | str | None = None,
        decided_by_member_id: UUID | str | None = None,
        mission_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Approval, Paginated[Approval]]:
        """List approvals, filtered by ``status`` (any of), ``kind``, the
        person asked, who decided, and the mission. The returned pager
        streams every approval; ``.page()`` reads the first page only."""
        statuses = [str(s) for s in status] if status else None
        kind_value = str(kind) if kind is not None else None
        logger.debug(
            "aauth approvals listed",
            extra={
                "status": statuses,
                "kind": kind_value,
                "mission_id": _id(mission_id),
            },
        )
        return self._paginate(
            "/v1/aauth/approvals",
            Paginated[Approval],
            {
                "status": statuses,
                "kind": kind_value,
                "member_id": _id(member_id),
                "decided_by_member_id": _id(decided_by_member_id),
                "mission_id": _id(mission_id),
                "limit": limit,
                "next": next,
            },
        )

    async def get(self, approval_id: UUID | str) -> Approval:
        """Read one approval; an unknown id is a ``NotFoundError``."""
        return await self._call(
            "GET", f"/v1/aauth/approvals/{approval_id}", Approval
        )

    async def decide(
        self,
        approval_id: UUID | str,
        *,
        status: ApprovalStatus | str,
        member_id: UUID | str | None = None,
        identity: ApproverIdentity | dict[str, str] | None = None,
        budget: Budget | dict[str, object] | None = None,
    ) -> Approval:
        """Record the approver's answer (``approved`` or ``denied``) and
        return the decided approval; approving does what the agent asked.

        The decider is a project ``member_id`` or the customer's own
        ``identity`` (``user_id`` or ``anonymous_id``), exactly one of the
        two. ``budget`` grants less than the agent asked for."""
        decision = ApprovalDecision.model_validate(
            {
                "status": status,
                "decided_by": {"member_id": member_id, "identity": identity},
                "budget": budget,
            }
        )
        approval = await self._call(
            "PATCH",
            f"/v1/aauth/approvals/{approval_id}",
            Approval,
            json=decision.model_dump(mode="json", exclude_none=True),
        )
        logger.debug(
            "aauth approval decided",
            extra={"approval_id": str(approval_id), "status": str(status)},
        )
        return approval


class AsyncAAuth:
    """DP ``/v1/aauth`` namespace: :attr:`missions` and :attr:`approvals`."""

    missions: AsyncMissions
    approvals: AsyncApprovals

    def __init__(self, http: _AsyncHttpClient) -> None:
        self.missions = AsyncMissions(http)
        self.approvals = AsyncApprovals(http)
