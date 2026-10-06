"""``client.connections`` / ``runner.connections`` — DP namespace for
``/v1/connections``: the apps (Gmail, Slack, ...) members connected for
themselves, which the agent then acts with in that member's sessions.

These are distinct from a connector's connections
(``client.connectors.connections``, CP ``/v1/connectors/{id}/connections``),
which an integrator administers for the project.

The routes take the ``connections:read``, ``connections:write`` and
``connections:delete`` scopes. A caller who is not a project administrator
only ever sees and manages their own connections, whatever ``member_id``
it asks for.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.connections import (
    Connection,
    ConnectionCreateRequest,
    ConnectPage,
)
from introspection_sdk.schemas.pagination import Paginated

CONNECTIONS_PATH = "/v1/connections"


def _path(connection_id: UUID | str) -> str:
    return f"{CONNECTIONS_PATH}/{quote(str(connection_id), safe='')}"


def _list_params(
    *,
    member_id: UUID | str | None,
    app: str | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "member_id": str(member_id) if member_id else None,
        "app": app,
        "limit": limit,
        "next": cursor,
    }


def _create_body(app: str, runtime: str | UUID) -> dict[str, Any]:
    return ConnectionCreateRequest(app=app, runtime=str(runtime)).model_dump(
        mode="json"
    )


def _runner_runtime(
    runtime: str | UUID | None, runtime_group_id: UUID | None
) -> str | UUID:
    if runtime is not None:
        return runtime
    if runtime_group_id is None:
        raise ValueError(
            "This runner's runtime context has no runtime_group_id, so "
            "runner.connections.create() cannot say which runtime's sessions "
            "use the connection. Pass runtime= explicitly, or open the "
            "runner from a runtime with client.runtimes(...).run()."
        )
    return runtime_group_id


class AppConnections:
    """DP ``/v1/connections`` namespace."""

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        app: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Connection, Paginated[Connection]]:
        """List connections. Iterate the returned :class:`Pager` to stream
        every connection across pages, or call ``.page()`` for the first
        page only.

        ``member_id`` narrows to one member's connections; a caller who is
        not a project administrator always gets only their own. ``app``
        narrows to one provider application slug."""

        def fetch(cursor: str | None) -> Paginated[Connection]:
            params = _list_params(
                member_id=member_id, app=app, limit=limit, cursor=cursor
            )
            payload = self._http.request(
                "GET", CONNECTIONS_PATH, params=params
            )
            return Paginated[Connection].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(self, *, app: str, runtime: str | UUID) -> ConnectPage:
        """A connect page for one app, for the caller themself.

        ``app`` is the provider application slug, such as ``gmail``
        (lowercase letters, digits, ``_`` and ``-``). ``runtime`` is the
        runtime slug or runtime group id whose sessions use the connection.
        Hand the member :attr:`ConnectPage.authorize_url`; it ends on a page
        saying the app is connected.
        """
        payload = self._http.request(
            "POST", CONNECTIONS_PATH, json=_create_body(app, runtime)
        )
        return ConnectPage.model_validate(payload)

    def get(self, connection_id: UUID | str) -> Connection:
        """Read one connection."""
        return Connection.model_validate(
            self._http.request("GET", _path(connection_id))
        )

    def delete(self, connection_id: UUID | str) -> None:
        """Remove one connection."""
        self._http.request("DELETE", _path(connection_id), expect="empty")


class RunnerAppConnections(AppConnections):
    """``runner.connections``: :class:`AppConnections` whose ``create``
    defaults ``runtime`` to the runner's runtime group."""

    def __init__(
        self, http: _HttpClient, runtime_group_id: UUID | None
    ) -> None:
        super().__init__(http)
        self._runtime_group_id = runtime_group_id

    def create(
        self, *, app: str, runtime: str | UUID | None = None
    ) -> ConnectPage:
        """A connect page for one app, used by this runner's runtime group
        unless ``runtime`` names another. Raises :class:`ValueError` when
        neither is known."""
        return super().create(
            app=app, runtime=_runner_runtime(runtime, self._runtime_group_id)
        )


class AsyncAppConnections:
    """Async twin of :class:`AppConnections` (DP ``/v1/connections``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        app: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Connection, Paginated[Connection]]:
        """Async twin of :meth:`AppConnections.list`."""

        async def fetch(cursor: str | None) -> Paginated[Connection]:
            params = _list_params(
                member_id=member_id, app=app, limit=limit, cursor=cursor
            )
            payload = await self._http.request(
                "GET", CONNECTIONS_PATH, params=params
            )
            return Paginated[Connection].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(self, *, app: str, runtime: str | UUID) -> ConnectPage:
        """Async twin of :meth:`AppConnections.create`."""
        payload = await self._http.request(
            "POST", CONNECTIONS_PATH, json=_create_body(app, runtime)
        )
        return ConnectPage.model_validate(payload)

    async def get(self, connection_id: UUID | str) -> Connection:
        """Async twin of :meth:`AppConnections.get`."""
        return Connection.model_validate(
            await self._http.request("GET", _path(connection_id))
        )

    async def delete(self, connection_id: UUID | str) -> None:
        """Async twin of :meth:`AppConnections.delete`."""
        await self._http.request(
            "DELETE", _path(connection_id), expect="empty"
        )


class AsyncRunnerAppConnections(AsyncAppConnections):
    """Async twin of :class:`RunnerAppConnections`."""

    def __init__(
        self, http: _AsyncHttpClient, runtime_group_id: UUID | None
    ) -> None:
        super().__init__(http)
        self._runtime_group_id = runtime_group_id

    async def create(
        self, *, app: str, runtime: str | UUID | None = None
    ) -> ConnectPage:
        """Async twin of :meth:`RunnerAppConnections.create`."""
        return await super().create(
            app=app, runtime=_runner_runtime(runtime, self._runtime_group_id)
        )
