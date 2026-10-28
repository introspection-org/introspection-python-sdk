"""Re-exported by :mod:`introspection_sdk.resources.projects`."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.projects import (
    Project,
    ProjectCreate,
    ProjectUpdate,
)
from introspection_sdk.schemas.runtime_peerings import RuntimePeering


def _project_path(project: str | UUID) -> str:
    return f"/v1/projects/{quote(str(project), safe='')}"


class AsyncProjectPeerings(_AsyncResource):
    """CP ``/v1/projects/{project}/peerings``: the runtime groups a project
    offers other projects, and with ``granted=True`` the ones offered to it.

    Read-only: offering, changing and ending a peering is a person's act in
    the web app, and no API key or Application holds that scope.
    """

    def list(
        self,
        project: str | UUID,
        runtime: str | UUID | None = None,
        *,
        granted: bool = False,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[RuntimePeering, Paginated[RuntimePeering]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List the peerings ``project`` (slug or id) offers; ``runtime`` (a
        runtime group slug or id) narrows them to that group's.
        ``granted=True`` lists the peerings other projects grant this one
        instead, and takes no ``runtime``. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every peering."""
        # unasync: end
        """List the peerings ``project`` (slug or id) offers; ``runtime`` (a
        runtime group slug or id) narrows them to that group's.
        ``granted=True`` lists the peerings other projects grant this one
        instead, and takes no ``runtime``. Iterate the returned
        :class:`Pager` to stream every peering, or call ``.page()`` for the
        first page only."""
        return self._paginate(
            f"{_project_path(project)}/peerings",
            Paginated[RuntimePeering],
            {
                "runtime": str(runtime) if runtime is not None else None,
                "granted": granted or None,
                "limit": limit,
                "next": next,
            },
        )

    async def get(
        self, project: str | UUID, peering_id: UUID | str
    ) -> RuntimePeering:
        """Read one peering ``project`` offers or one that admits it; any
        other raises :class:`~introspection_sdk.NotFoundError`."""
        return await self._call(
            "GET",
            f"{_project_path(project)}/peerings/{quote(str(peering_id), safe='')}",
            RuntimePeering,
        )


class AsyncProjects(_AsyncResource):
    """CP ``/v1/projects`` namespace: the credential's org's projects,
    addressed by slug or id, with the runtime ``peerings`` each offers."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        super().__init__(http)
        self.peerings = AsyncProjectPeerings(http)

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
        return await self._call("GET", _project_path(project), Project)

    async def create(
        self,
        *,
        name: str,
        deployment_id: UUID | str,
        slug: str | None = None,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
        include_ark: bool | None = None,
    ) -> Project:
        """Create a project on the Data Plane ``deployment_id`` names (an
        existing project's :attr:`~Project.deployment_id`). ``slug`` is the
        stable identifier the CLI and dashboard URLs use."""
        body = _body(
            ProjectCreate,
            {
                "name": name,
                "deployment_id": deployment_id,
                "slug": slug,
                "description": description,
                "settings": settings,
                "include_ark": include_ark,
            },
        )
        return await self._call("POST", "/v1/projects", Project, json=body)

    async def update(
        self,
        project: str | UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Project:
        """Update a project by slug or id; only the fields given are sent,
        and a call with none is a 400 (no fields to update)."""
        body = _body(
            ProjectUpdate,
            {"name": name, "description": description, "settings": settings},
        )
        return await self._call(
            "PATCH", _project_path(project), Project, json=body
        )

    async def delete(self, project: str | UUID) -> None:
        """Delete a project by slug or id, with everything in it."""
        await self._delete(_project_path(project))
