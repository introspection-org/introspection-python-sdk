"""Re-exported by :mod:`introspection_sdk.resources.projects`."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _project,
)
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.projects import Project


class AsyncProjects(_AsyncResource):
    """CP ``/v1/projects`` namespace: the credential's org's projects,
    addressed by slug or id. Read-only."""

    def list(
        self,
        *,
        project: str | UUID | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Project, Paginated[Project]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List the org's projects; ``project`` (slug or id) narrows it to
        one. ``await`` the returned :class:`AsyncPager` for the first page,
        or ``async for`` it to stream every project."""
        # unasync: end
        """List the org's projects; ``project`` (slug or id) narrows it to
        one. Iterate the returned :class:`Pager` to stream every project,
        or call ``.page()`` for the first page only."""
        return self._paginate(
            "/v1/projects",
            Paginated[Project],
            {**_project(project), "limit": limit, "next": next},
        )

    async def get(self, project: str | UUID) -> Project:
        """Read a project by slug or id. One outside the credential's org
        raises :class:`~introspection_sdk.NotFoundError`."""
        return await self._call(
            "GET", f"/v1/projects/{quote(str(project), safe='')}", Project
        )
