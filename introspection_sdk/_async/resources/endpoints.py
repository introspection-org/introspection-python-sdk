"""Re-exported by :mod:`introspection_sdk.resources.endpoints`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.endpoints import (
    Endpoint,
    EndpointKind,
    EndpointMetadata,
    EndpointUpdate,
)
from introspection_sdk.schemas.pagination import Paginated


class AsyncEndpoints(_AsyncResource):
    """CP ``/v1/endpoints`` namespace: the upstream hosts a project's
    runtimes reach. An MCP server's endpoint is made by the connection that
    binds it (:meth:`Connectors.authorize`); this namespace reads, edits and
    removes them."""

    def list(
        self,
        *,
        project: str | UUID | None = None,
        kind: EndpointKind | str | None = None,
        runtime_id: UUID | str | None = None,
        runtime: str | None = None,
        environment: str | None = None,
        mcp_server_id: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Endpoint, Paginated[Endpoint]]:
        """List the project's endpoints. The returned pager streams every
        endpoint; ``.page()`` reads the first page only.

        Filters AND together: ``kind``, the runtime they are pinned to (by
        ``runtime_id``, or ``runtime`` as a slug or group id), the
        ``environment``, and ``mcp_server_id`` for an MCP binding."""
        return self._paginate(
            "/v1/endpoints",
            Paginated[Endpoint],
            {
                **_project(project),
                "kind": str(kind) if kind is not None else None,
                "runtime_id": str(runtime_id) if runtime_id else None,
                "runtime": runtime,
                "environment": environment,
                "mcp_server_id": mcp_server_id,
                "limit": limit,
                "next": next,
            },
        )

    async def get(
        self, endpoint_id: UUID | str, *, project: str | UUID | None = None
    ) -> Endpoint:
        return await self._call(
            "GET",
            f"/v1/endpoints/{endpoint_id}",
            Endpoint,
            params=_project(project),
        )

    async def update(
        self,
        endpoint_id: UUID | str,
        *,
        project: str | UUID | None = None,
        name: str | None = None,
        host: str | None = None,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        kind: EndpointKind | str | None = None,
        metadata: EndpointMetadata | dict[str, Any] | None = None,
        assertion_claims: dict[str, Any] | None = None,
        runtime_id: UUID | str | None = None,
        runtime_group_id: UUID | str | None = None,
        environment: str | None = None,
        verify_path: str | None = None,
        authorized_application_id: UUID | str | None = None,
    ) -> Endpoint:
        """Update an endpoint; only the fields given are sent."""
        body = _body(
            EndpointUpdate,
            {
                "name": name,
                "host": host,
                "base_url": base_url,
                "headers": headers,
                "kind": kind,
                "metadata": metadata,
                "assertion_claims": assertion_claims,
                "runtime_id": runtime_id,
                "runtime_group_id": runtime_group_id,
                "environment": environment,
                "verify_path": verify_path,
                "authorized_application_id": authorized_application_id,
            },
        )
        return await self._call(
            "PATCH",
            f"/v1/endpoints/{endpoint_id}",
            Endpoint,
            params=_project(project),
            json=body,
        )

    async def delete(
        self, endpoint_id: UUID | str, *, project: str | UUID | None = None
    ) -> None:
        await self._delete(f"/v1/endpoints/{endpoint_id}", _project(project))
