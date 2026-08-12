"""``client.connectors`` — CP namespace for ``/v1/connectors``.

Connectors are provider integrations (Slack, Gmail, Stripe, ...) a
project owns; connections are the authorized subjects living under
them (``client.connectors.connections.*``). ``authorize`` mints the
consent URL a Business hands its customer — the SDK presents it as a
connector operation even though the route lives under ``/v1/oauth/``.

``client_secret`` / ``signing_secret`` are write-only: accepted on
create and update, absent from every response, and omitting them on
update means "unchanged". Project scope comes from the authenticated
credential; connector calls do not take a separate project selector.
"""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.connectors import (
    Connection,
    ConnectionAuthorizationPending,
    ConnectionBrokerSubjectType,
    ConnectionCreateRequest,
    ConnectionCreateSubjectType,
    ConnectionMissionConstraints,
    ConnectionToken,
    ConnectionTokenRequest,
    ConnectionTokenResult,
    Connector,
    ConnectorApprovalPolicy,
    ConnectorAuthMode,
    ConnectorAuthorization,
    ConnectorAuthorizeRequest,
    ConnectorCreateRequest,
    ConnectorPersonServerMode,
    ConnectorStatus,
    ConnectorUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runner import RunnerIdentity


def _create_body(
    *,
    name: str,
    provider: str,
    auth_mode: ConnectorAuthMode | str,
    slug: str | None,
    environment: str | None,
    agent_member_id: UUID | None,
    authorization_endpoint: str | None,
    token_endpoint: str | None,
    scopes: list[str] | None,
    api_hosts: list[str] | None,
    client_id: str | None,
    client_secret: str | None,
    signing_secret: str | None,
    metadata: dict[str, Any] | None,
    issuer: str | None,
    person_server_mode: ConnectorPersonServerMode | str | None,
    person_server_url: str | None,
    approval_policy: ConnectorApprovalPolicy | str | None,
    application_id: UUID | None,
    assertion_audience: str | None,
    webhook_url: str | None,
) -> dict[str, Any]:
    # Loose public inputs (plain str) are coerced by validation:
    # str -> ConnectorAuthMode. Secrets ride the body as-is; the API
    # stores them encrypted and never returns them.
    return ConnectorCreateRequest.model_validate(
        {
            "name": name,
            "provider": provider,
            "auth_mode": auth_mode,
            "slug": slug,
            "environment": environment,
            "agent_member_id": agent_member_id,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "scopes": scopes,
            "api_hosts": api_hosts,
            "client_id": client_id,
            "client_secret": client_secret,
            "signing_secret": signing_secret,
            "metadata": metadata,
            "issuer": issuer,
            "person_server_mode": person_server_mode,
            "person_server_url": person_server_url,
            "approval_policy": approval_policy,
            "application_id": application_id,
            "assertion_audience": assertion_audience,
            "webhook_url": webhook_url,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    agent_member_id: UUID | None,
    scopes: list[str] | None,
    api_hosts: list[str] | None,
    status: ConnectorStatus | str | None,
    metadata: dict[str, Any] | None,
    webhook_url: str | None,
    client_secret: str | None,
    signing_secret: str | None,
) -> dict[str, Any]:
    # `exclude_none` is the "omitted = unchanged" contract: a secret
    # left as None never reaches the wire, so it cannot be cleared.
    return ConnectorUpdateRequest.model_validate(
        {
            "name": name,
            "agent_member_id": agent_member_id,
            "scopes": scopes,
            "api_hosts": api_hosts,
            "status": status,
            "metadata": metadata,
            "webhook_url": webhook_url,
            "client_secret": client_secret,
            "signing_secret": signing_secret,
        }
    ).model_dump(mode="json", exclude_none=True)


def _authorize_body(
    *,
    connector_id: UUID,
    runtime: str | UUID | None,
    subject: ConnectionBrokerSubjectType | str | None,
    return_url: str | None,
    expires_in: int | None,
    identity: RunnerIdentity | dict[str, Any] | None,
) -> dict[str, Any]:
    return ConnectorAuthorizeRequest.model_validate(
        {
            "connector_id": connector_id,
            "runtime": str(runtime) if runtime is not None else None,
            "subject": subject,
            "return_url": return_url,
            "expires_in": expires_in,
            "identity": identity,
        }
    ).model_dump(mode="json", exclude_none=True)


def _connection_create_body(
    *,
    access_token: str,
    subject_type: ConnectionCreateSubjectType | str | None,
    scopes_granted: list[str] | None,
    refresh_token: str | None,
    token_expires_at: Any,
) -> dict[str, Any]:
    return ConnectionCreateRequest.model_validate(
        {
            "access_token": access_token,
            "subject_type": subject_type,
            "scopes_granted": scopes_granted,
            "refresh_token": refresh_token,
            "token_expires_at": token_expires_at,
        }
    ).model_dump(mode="json", exclude_none=True)


def _token_body(
    *,
    connector_id: UUID,
    subject: ConnectionBrokerSubjectType | str | None,
    action: str | None,
    requested_permissions: ConnectionMissionConstraints
    | dict[str, Any]
    | None,
) -> dict[str, Any]:
    return ConnectionTokenRequest.model_validate(
        {
            "connector_id": connector_id,
            "subject": subject,
            "action": action,
            "requested_permissions": requested_permissions,
        }
    ).model_dump(mode="json", exclude_none=True, exclude_defaults=True)


def _token_result(payload: Any) -> ConnectionTokenResult:
    if (
        isinstance(payload, dict)
        and payload.get("status") == "authorization_pending"
    ):
        return ConnectionAuthorizationPending.model_validate(payload)
    return ConnectionToken.model_validate(payload)


class Connections:
    """CP ``/v1/connectors/{connector_id}/connections`` namespace.

    Connections are addressed by connector id and take no ``project``
    parameter. ``revoke`` (not ``delete``) destroys the provider token.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        connector_id: UUID,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Connection, Paginated[Connection]]:
        """List a connector's connections. Iterate the returned
        :class:`Pager` to stream every connection across pages, or call
        ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[Connection]:
            params: dict[str, Any] = {"limit": limit, "next": cursor}
            payload = self._http.request(
                "GET",
                f"/v1/connectors/{connector_id}/connections",
                params=params,
            )
            return Paginated[Connection].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        connector_id: UUID,
        *,
        access_token: str,
        subject_type: ConnectionCreateSubjectType | str | None = None,
        scopes_granted: builtins.list[str] | None = None,
        refresh_token: str | None = None,
        token_expires_at: Any = None,
    ) -> Connection:
        """Register a connection with a caller-supplied provider token
        (registered mode). Tokens are write-only — stored encrypted,
        never returned."""
        payload = self._http.request(
            "POST",
            f"/v1/connectors/{connector_id}/connections",
            json=_connection_create_body(
                access_token=access_token,
                subject_type=subject_type,
                scopes_granted=scopes_granted,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
            ),
        )
        return Connection.model_validate(payload)

    def get_token(
        self,
        connector_id: UUID,
        *,
        subject: ConnectionBrokerSubjectType | str | None = None,
        action: str | None = None,
        requested_permissions: ConnectionMissionConstraints
        | dict[str, Any]
        | None = None,
    ) -> ConnectionTokenResult:
        """Resolve a provider token, or a pending human-approval mission."""
        payload = self._http.request(
            "POST",
            "/v1/oauth/connections/token",
            json=_token_body(
                connector_id=connector_id,
                subject=subject,
                action=action,
                requested_permissions=requested_permissions,
            ),
        )
        return _token_result(payload)

    def get(self, connector_id: UUID, connection_id: UUID) -> Connection:
        payload = self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}/connections/{connection_id}",
        )
        return Connection.model_validate(payload)

    def revoke(self, connector_id: UUID, connection_id: UUID) -> None:
        """Revoke a connection — destroys the stored provider token."""
        self._http.request(
            "DELETE",
            f"/v1/connectors/{connector_id}/connections/{connection_id}",
            expect="empty",
        )


class Connectors:
    """CP ``/v1/connectors`` namespace.

    Connector CRUD uses the project carried by the authenticated
    credential. Nested ``connections`` and ``authorize`` are addressed
    by connector id alone.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http
        self.connections = Connections(http)

    def list(
        self,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Connector, Paginated[Connector]]:
        """List connectors. Iterate the returned :class:`Pager` to
        stream every connector across pages, or call ``.page()`` for the
        first page only."""

        def fetch(cursor: str | None) -> Paginated[Connector]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
            }
            payload = self._http.request(
                "GET", "/v1/connectors", params=params
            )
            return Paginated[Connector].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        name: str,
        provider: str,
        auth_mode: ConnectorAuthMode | str,
        slug: str | None = None,
        environment: str | None = None,
        agent_member_id: UUID | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        scopes: builtins.list[str] | None = None,
        api_hosts: builtins.list[str] | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        signing_secret: str | None = None,
        metadata: dict[str, Any] | None = None,
        issuer: str | None = None,
        person_server_mode: ConnectorPersonServerMode | str | None = None,
        person_server_url: str | None = None,
        approval_policy: ConnectorApprovalPolicy | str | None = None,
        application_id: UUID | None = None,
        assertion_audience: str | None = None,
        webhook_url: str | None = None,
    ) -> Connector:
        """Create a connector (idempotent on ``slug``).

        ``client_secret`` / ``signing_secret`` are write-only — never
        returned on any read. Pass ``issuer`` to have the server resolve
        the OAuth endpoints from ``.well-known`` discovery.
        """
        payload = self._http.request(
            "POST",
            "/v1/connectors",
            json=_create_body(
                name=name,
                provider=provider,
                auth_mode=auth_mode,
                slug=slug,
                environment=environment,
                agent_member_id=agent_member_id,
                authorization_endpoint=authorization_endpoint,
                token_endpoint=token_endpoint,
                scopes=scopes,
                api_hosts=api_hosts,
                client_id=client_id,
                client_secret=client_secret,
                signing_secret=signing_secret,
                metadata=metadata,
                issuer=issuer,
                person_server_mode=person_server_mode,
                person_server_url=person_server_url,
                approval_policy=approval_policy,
                application_id=application_id,
                assertion_audience=assertion_audience,
                webhook_url=webhook_url,
            ),
        )
        return Connector.model_validate(payload)

    def get(self, connector_id: UUID) -> Connector:
        payload = self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}",
        )
        return Connector.model_validate(payload)

    def update(
        self,
        connector_id: UUID,
        *,
        name: str | None = None,
        agent_member_id: UUID | None = None,
        scopes: builtins.list[str] | None = None,
        api_hosts: builtins.list[str] | None = None,
        status: ConnectorStatus | str | None = None,
        metadata: dict[str, Any] | None = None,
        webhook_url: str | None = None,
        client_secret: str | None = None,
        signing_secret: str | None = None,
    ) -> Connector:
        """Update a connector. Only provided fields change; an omitted
        ``client_secret`` / ``signing_secret`` stays as it is (write-only
        rotation, never a clear)."""
        payload = self._http.request(
            "PATCH",
            f"/v1/connectors/{connector_id}",
            json=_update_body(
                name=name,
                agent_member_id=agent_member_id,
                scopes=scopes,
                api_hosts=api_hosts,
                status=status,
                metadata=metadata,
                webhook_url=webhook_url,
                client_secret=client_secret,
                signing_secret=signing_secret,
            ),
        )
        return Connector.model_validate(payload)

    def delete(self, connector_id: UUID) -> None:
        """Soft-delete a connector; its connections are revoked."""
        self._http.request(
            "DELETE",
            f"/v1/connectors/{connector_id}",
            expect="empty",
        )

    def authorize(
        self,
        connector_id: UUID,
        *,
        runtime: str | UUID | None = None,
        subject: ConnectionBrokerSubjectType | str | None = None,
        return_url: str | None = None,
        expires_in: int | None = None,
        identity: RunnerIdentity | dict[str, Any] | None = None,
    ) -> ConnectorAuthorization:
        """Mint a consent URL for the connector
        (``POST /v1/oauth/connections/authorize``).

        Each call writes a fresh single-use ``state``: two calls give
        two different URLs, and the response must never be cached. The
        URL stays valid for ``expires_in`` seconds (60–86400, default
        600) — raise it when handing the link to someone else to open. A
        connector with ``requires_runtime=True`` 422s unless ``runtime``
        (slug or runtime group id) names the agent that replies.

        ``identity`` asserts the end customer the grant is for: its
        ``user_id`` resolves a ``customer`` member recorded as the
        connection's ``created_by_member_id``, so a partner can associate
        the connection with their own caller rather than the agent member
        that made the API call. Omit to attribute the grant to the
        authenticated principal. Asserting one mints a ``customer``
        member, so it can raise
        :class:`~introspection_sdk.ConflictError` (409) when the org has
        reached its member limit — a plan conflict, not back-pressure.
        """
        payload = self._http.request(
            "POST",
            "/v1/oauth/connections/authorize",
            json=_authorize_body(
                connector_id=connector_id,
                runtime=runtime,
                subject=subject,
                return_url=return_url,
                expires_in=expires_in,
                identity=identity,
            ),
        )
        return ConnectorAuthorization.model_validate(payload)


class AsyncConnections:
    """Async twin of :class:`Connections`
    (CP ``/v1/connectors/{connector_id}/connections``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        connector_id: UUID,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Connection, Paginated[Connection]]:
        """List a connector's connections. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every connection across pages."""

        async def fetch(cursor: str | None) -> Paginated[Connection]:
            params: dict[str, Any] = {"limit": limit, "next": cursor}
            payload = await self._http.request(
                "GET",
                f"/v1/connectors/{connector_id}/connections",
                params=params,
            )
            return Paginated[Connection].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        connector_id: UUID,
        *,
        access_token: str,
        subject_type: ConnectionCreateSubjectType | str | None = None,
        scopes_granted: builtins.list[str] | None = None,
        refresh_token: str | None = None,
        token_expires_at: Any = None,
    ) -> Connection:
        """Register a connection with a caller-supplied provider token
        (registered mode). Tokens are write-only — stored encrypted,
        never returned."""
        payload = await self._http.request(
            "POST",
            f"/v1/connectors/{connector_id}/connections",
            json=_connection_create_body(
                access_token=access_token,
                subject_type=subject_type,
                scopes_granted=scopes_granted,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
            ),
        )
        return Connection.model_validate(payload)

    async def get_token(
        self,
        connector_id: UUID,
        *,
        subject: ConnectionBrokerSubjectType | str | None = None,
        action: str | None = None,
        requested_permissions: ConnectionMissionConstraints
        | dict[str, Any]
        | None = None,
    ) -> ConnectionTokenResult:
        """Resolve a provider token, or a pending human-approval mission."""
        payload = await self._http.request(
            "POST",
            "/v1/oauth/connections/token",
            json=_token_body(
                connector_id=connector_id,
                subject=subject,
                action=action,
                requested_permissions=requested_permissions,
            ),
        )
        return _token_result(payload)

    async def get(self, connector_id: UUID, connection_id: UUID) -> Connection:
        payload = await self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}/connections/{connection_id}",
        )
        return Connection.model_validate(payload)

    async def revoke(self, connector_id: UUID, connection_id: UUID) -> None:
        """Revoke a connection — destroys the stored provider token."""
        await self._http.request(
            "DELETE",
            f"/v1/connectors/{connector_id}/connections/{connection_id}",
            expect="empty",
        )


class AsyncConnectors:
    """Async twin of :class:`Connectors` (CP ``/v1/connectors``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.connections = AsyncConnections(http)

    def list(
        self,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Connector, Paginated[Connector]]:
        """List connectors. ``await`` the returned :class:`AsyncPager`
        for the first page, or ``async for`` it to stream every
        connector across pages."""

        async def fetch(cursor: str | None) -> Paginated[Connector]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/connectors", params=params
            )
            return Paginated[Connector].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        name: str,
        provider: str,
        auth_mode: ConnectorAuthMode | str,
        slug: str | None = None,
        environment: str | None = None,
        agent_member_id: UUID | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        scopes: builtins.list[str] | None = None,
        api_hosts: builtins.list[str] | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        signing_secret: str | None = None,
        metadata: dict[str, Any] | None = None,
        issuer: str | None = None,
        person_server_mode: ConnectorPersonServerMode | str | None = None,
        person_server_url: str | None = None,
        approval_policy: ConnectorApprovalPolicy | str | None = None,
        application_id: UUID | None = None,
        assertion_audience: str | None = None,
        webhook_url: str | None = None,
    ) -> Connector:
        """Create a connector (idempotent on ``slug``).

        ``client_secret`` / ``signing_secret`` are write-only — never
        returned on any read. Pass ``issuer`` to have the server resolve
        the OAuth endpoints from ``.well-known`` discovery.
        """
        payload = await self._http.request(
            "POST",
            "/v1/connectors",
            json=_create_body(
                name=name,
                provider=provider,
                auth_mode=auth_mode,
                slug=slug,
                environment=environment,
                agent_member_id=agent_member_id,
                authorization_endpoint=authorization_endpoint,
                token_endpoint=token_endpoint,
                scopes=scopes,
                api_hosts=api_hosts,
                client_id=client_id,
                client_secret=client_secret,
                signing_secret=signing_secret,
                metadata=metadata,
                issuer=issuer,
                person_server_mode=person_server_mode,
                person_server_url=person_server_url,
                approval_policy=approval_policy,
                application_id=application_id,
                assertion_audience=assertion_audience,
                webhook_url=webhook_url,
            ),
        )
        return Connector.model_validate(payload)

    async def get(self, connector_id: UUID) -> Connector:
        payload = await self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}",
        )
        return Connector.model_validate(payload)

    async def update(
        self,
        connector_id: UUID,
        *,
        name: str | None = None,
        agent_member_id: UUID | None = None,
        scopes: builtins.list[str] | None = None,
        api_hosts: builtins.list[str] | None = None,
        status: ConnectorStatus | str | None = None,
        metadata: dict[str, Any] | None = None,
        webhook_url: str | None = None,
        client_secret: str | None = None,
        signing_secret: str | None = None,
    ) -> Connector:
        """Update a connector. Only provided fields change; an omitted
        ``client_secret`` / ``signing_secret`` stays as it is (write-only
        rotation, never a clear)."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/connectors/{connector_id}",
            json=_update_body(
                name=name,
                agent_member_id=agent_member_id,
                scopes=scopes,
                api_hosts=api_hosts,
                status=status,
                metadata=metadata,
                webhook_url=webhook_url,
                client_secret=client_secret,
                signing_secret=signing_secret,
            ),
        )
        return Connector.model_validate(payload)

    async def delete(self, connector_id: UUID) -> None:
        """Soft-delete a connector; its connections are revoked."""
        await self._http.request(
            "DELETE",
            f"/v1/connectors/{connector_id}",
            expect="empty",
        )

    async def authorize(
        self,
        connector_id: UUID,
        *,
        runtime: str | UUID | None = None,
        subject: ConnectionBrokerSubjectType | str | None = None,
        return_url: str | None = None,
        expires_in: int | None = None,
        identity: RunnerIdentity | dict[str, Any] | None = None,
    ) -> ConnectorAuthorization:
        """Mint a consent URL for the connector
        (``POST /v1/oauth/connections/authorize``).

        Each call writes a fresh single-use ``state``: two calls give
        two different URLs, and the response must never be cached. The
        URL stays valid for ``expires_in`` seconds (60–86400, default
        600) — raise it when handing the link to someone else to open. A
        connector with ``requires_runtime=True`` 422s unless ``runtime``
        (slug or runtime group id) names the agent that replies.

        ``identity`` asserts the end customer the grant is for: its
        ``user_id`` resolves a ``customer`` member recorded as the
        connection's ``created_by_member_id``, so a partner can associate
        the connection with their own caller rather than the agent member
        that made the API call. Omit to attribute the grant to the
        authenticated principal. Asserting one mints a ``customer``
        member, so it can raise
        :class:`~introspection_sdk.ConflictError` (409) when the org has
        reached its member limit — a plan conflict, not back-pressure.
        """
        payload = await self._http.request(
            "POST",
            "/v1/oauth/connections/authorize",
            json=_authorize_body(
                connector_id=connector_id,
                runtime=runtime,
                subject=subject,
                return_url=return_url,
                expires_in=expires_in,
                identity=identity,
            ),
        )
        return ConnectorAuthorization.model_validate(payload)


__all__ = [
    "AsyncConnections",
    "AsyncConnectors",
    "Connections",
    "Connectors",
]
