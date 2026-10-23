"""Re-exported by :mod:`introspection_sdk.resources.judges`."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.judges import Judge, JudgeUpdateRequest
from introspection_sdk.schemas.pagination import Paginated


class AsyncJudges(_AsyncResource):
    """CP ``/v1/judges`` namespace: the judges a project's Recipes declare.

    A judge is authored in its Recipe and published with it, so there is no
    create or delete; an update changes only whether it runs and how often.
    ``project`` (slug or id) names the project when the credential does not.
    """

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime_group_id: UUID | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Judge, Paginated[Judge]]:
        """List judges, across pages."""
        return self._paginate(
            "/v1/judges",
            Paginated[Judge],
            {
                **_project(project),
                "runtime_group_id": (
                    str(runtime_group_id) if runtime_group_id else None
                ),
                "limit": limit,
                "next": next,
            },
        )

    async def get(
        self, judge_id: UUID, *, project: str | UUID | None = None
    ) -> Judge:
        return await self._call(
            "GET", f"/v1/judges/{judge_id}", Judge, params=_project(project)
        )

    async def update(
        self,
        judge_id: UUID,
        *,
        project: str | UUID | None = None,
        enabled: bool | None = None,
        sample_rate: float | None = None,
    ) -> Judge:
        """Turn a judge on or off, or change ``sample_rate`` (the fraction of
        conversations judged, ``0.0``-``1.0``)."""
        body = _body(
            JudgeUpdateRequest,
            {"enabled": enabled, "sample_rate": sample_rate},
        )
        return await self._call(
            "PATCH",
            f"/v1/judges/{judge_id}",
            Judge,
            params=_project(project),
            json=body,
        )
