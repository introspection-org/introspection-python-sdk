"""Async twins re-exported by :mod:`introspection_sdk.runner_resources.connections`."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.runner_resources._connections_common import (
    CONNECTIONS_PATH,
    _create_body,
    _list_params,
    _path,
    _runner_runtime,
)
from introspection_sdk.schemas.connections import (
    Connection,
    ConnectPage,
)
from introspection_sdk.schemas.pagination import Paginated


class AsyncAppConnections:
    """DP ``/v1/connections`` namespace."""

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
        """List connections. Iterate the returned :class:`Pager` to stream
        every connection across pages, or call ``.page()`` for the first
        page only.

        ``member_id`` narrows to one member's connections; a caller who is
        not a project administrator always gets only their own. ``app``
        narrows to one provider application slug."""

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
        """A connect page for one app, for the caller themself.

        ``app`` is the provider application slug, such as ``gmail``
        (lowercase letters, digits, ``_`` and ``-``). ``runtime`` is the
        runtime slug or runtime group id whose sessions use the connection.
        Hand the member :attr:`ConnectPage.authorize_url`; it ends on a page
        saying the app is connected.
        """
        payload = await self._http.request(
            "POST", CONNECTIONS_PATH, json=_create_body(app, runtime)
        )
        return ConnectPage.model_validate(payload)

    async def get(self, connection_id: UUID | str) -> Connection:
        """Read one connection."""
        return Connection.model_validate(
            await self._http.request("GET", _path(connection_id))
        )

    async def delete(self, connection_id: UUID | str) -> None:
        """Remove one connection."""
        await self._http.request(
            "DELETE", _path(connection_id), expect="empty"
        )


class AsyncRunnerAppConnections(AsyncAppConnections):
    """``runner.connections``: :class:`AppConnections` whose ``create``
    defaults ``runtime`` to the runner's runtime group."""

    def __init__(
        self, http: _AsyncHttpClient, runtime_group_id: UUID | None
    ) -> None:
        super().__init__(http)
        self._runtime_group_id = runtime_group_id

    async def create(
        self, *, app: str, runtime: str | UUID | None = None
    ) -> ConnectPage:
        """A connect page for one app, used by this runner's runtime group
        unless ``runtime`` names another. Raises :class:`ValueError` when
        neither is known."""
        return await super().create(
            app=app, runtime=_runner_runtime(runtime, self._runtime_group_id)
        )
