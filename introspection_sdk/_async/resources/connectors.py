"""Re-exported by :mod:`introspection_sdk.resources.connectors`."""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from introspection_sdk._async.resources._crud import _project
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk._strict_schema import decode
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.connectors import (
    ConnectionAuthorizationPending,
    ConnectionBrokerSubjectType,
    ConnectionMissionConstraints,
    ConnectionToken,
    ConnectionTokenRequest,
    ConnectionTokenResult,
    Connector,
    ConnectorApp,
    ConnectorAppList,
    ConnectorAuthMode,
    ConnectorAuthorization,
    ConnectorAuthorizeBinding,
    ConnectorAuthorizeRequest,
    ConnectorCreateRequest,
    ConnectorOAuthDiscoveryRequest,
    ConnectorOAuthDiscoveryResponse,
    ConnectorSecretResponse,
    ConnectorStatus,
    ConnectorUpdateRequest,
    PolicyEntity,
    WebhookAuth,
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
    person_server_url: str | None,
    application_id: UUID | None,
    assertion_audience: str | None,
    policy_entities: list[PolicyEntity | dict[str, Any]] | None,
    webhook_url: str | None,
    webhook_auth: WebhookAuth | str | None,
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
            "person_server_url": person_server_url,
            "application_id": application_id,
            "assertion_audience": assertion_audience,
            "policy_entities": policy_entities,
            "webhook_url": webhook_url,
            "webhook_auth": webhook_auth,
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
    policy_entities: list[PolicyEntity | dict[str, Any]] | None,
    client_secret: str | None,
    signing_secret: str | None,
    webhook_auth: WebhookAuth | str | None,
    rotate_signing_secret: bool,
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
            "policy_entities": policy_entities,
            "client_secret": client_secret,
            "signing_secret": signing_secret,
            "webhook_auth": webhook_auth,
            "rotate_signing_secret": rotate_signing_secret or None,
        }
    ).model_dump(mode="json", exclude_none=True)


def _authorize_body(
    *,
    connector_id: UUID | None,
    integration_id: UUID | None,
    runtime: str | UUID | None,
    subject: ConnectionBrokerSubjectType | str | None,
    return_url: str | None,
    expires_in: int | None,
    identity: RunnerIdentity | dict[str, Any] | None,
    app: str | None,
    allow_progressive_scopes: bool,
    binding: ConnectorAuthorizeBinding | dict[str, Any] | None,
) -> dict[str, Any]:
    return ConnectorAuthorizeRequest.model_validate(
        {
            "connector_id": connector_id,
            "integration_id": integration_id,
            "runtime": str(runtime) if runtime is not None else None,
            "subject": subject,
            "return_url": return_url,
            "expires_in": expires_in,
            "identity": identity,
            "app": app,
            "allow_progressive_scopes": allow_progressive_scopes,
            "binding": binding,
        }
    ).model_dump(mode="json", exclude_none=True, exclude_defaults=True)


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
        return decode(ConnectionAuthorizationPending, payload)
    return decode(ConnectionToken, payload)


class AsyncConnectors:
    """CP ``/v1/connectors`` namespace.

    Connector CRUD uses the project carried by the authenticated
    credential; :meth:`list` and :meth:`delete` take ``project`` for a
    credential that names none (an owner's session). ``authorize`` and
    ``get_token`` are addressed by connector id alone. A connector's
    connections are read and deleted through the data plane's
    ``connections`` namespace (``client.connections``).
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        project: str | UUID | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Connector, Paginated[Connector]]:
        """List connectors. The returned pager streams every connector across
        pages; ``.page()`` reads the first page only. ``project`` (slug or
        id) is needed only when the credential does not name one."""

        async def fetch(cursor: str | None) -> Paginated[Connector]:
            params: dict[str, Any] = {
                **_project(project),
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/connectors", params=params
            )
            return decode(Paginated[Connector], payload)

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
        person_server_url: str | None = None,
        application_id: UUID | None = None,
        assertion_audience: str | None = None,
        policy_entities: builtins.list[PolicyEntity | dict[str, Any]]
        | None = None,
        webhook_url: str | None = None,
        webhook_auth: WebhookAuth | str | None = None,
    ) -> ConnectorSecretResponse:
        """Create a connector, or replace one with the same ``slug``.

        ``slug`` is unique per project. A repeat create with a live slug
        replaces that connector's configuration (name, environment,
        endpoints, scopes, api hosts, client id, metadata, ...) and keeps
        its ``provider``, ``auth_mode`` and stored secrets, so re-running
        a create never duplicates the connector.

        ``client_secret`` / ``signing_secret`` are write-only — never
        returned on any read. Pass ``issuer`` to have the server resolve
        the OAuth endpoints from ``.well-known`` discovery and, where the
        provider supports it, register an OAuth client on its own. A
        ``pipedream`` connector requires ``metadata["provider_workspace_id"]``
        — its Pipedream Connect project id (``proj_...``). An ``aauth``
        connector requires ``person_server_url`` and ``application_id``;
        ``policy_entities`` are the Cedar entities the egress policy gate
        adds to its requests.

        A ``webhook`` connector (``provider="webhook"``,
        ``auth_mode="static"``) is inbound only: the customer's systems
        call the control plane's ``/v1/webhooks/connectors/{id}``, and a
        routine's ``connector`` trigger runs on those calls.
        ``webhook_auth`` picks how callers authenticate
        (``standard_webhooks``, the default, or ``bearer``). The platform
        generates its secret and returns it once, as ``signing_secret``
        on the response; send no secret.
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
                person_server_url=person_server_url,
                application_id=application_id,
                assertion_audience=assertion_audience,
                policy_entities=policy_entities,
                webhook_url=webhook_url,
                webhook_auth=webhook_auth,
            ),
        )
        return decode(ConnectorSecretResponse, payload)

    async def list_apps(
        self,
        connector_id: UUID,
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> builtins.list[ConnectorApp]:
        """Search a connector's provider application catalogue."""
        payload = await self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}/apps",
            params={"q": query, "limit": limit},
        )
        return decode(ConnectorAppList, payload).data

    async def search_custom_apps(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> builtins.list[ConnectorApp]:
        """Search the open MCP registry — the catalogue a custom connector
        picks from (``GET /v1/connectors/custom/apps``).

        Takes no connector and no project: it is read before any
        connector exists. ``query`` is 2–100 characters; ``limit`` is
        1–50 (server default 20). A listing's ``mcp_url`` is what to pass
        to :meth:`discover_oauth` and ``create(issuer=...)``.
        """
        payload = await self._http.request(
            "GET",
            "/v1/connectors/custom/apps",
            params={"q": query, "limit": limit},
        )
        return decode(ConnectorAppList, payload).data

    async def discover_oauth(
        self, issuer: str
    ) -> ConnectorOAuthDiscoveryResponse:
        """Resolve a provider's OAuth metadata before creating a connector
        (``POST /v1/connectors/discover-oauth``).

        ``issuer`` is an authorization-server issuer URL or an MCP server
        URL. Discovery may REGISTER an OAuth client with the provider
        (dynamic registration) and return its ``client_id`` /
        ``client_secret`` — pass those to :meth:`create` so a second
        client is not registered. ``create`` with only ``issuer`` also
        discovers and registers on its own. Raises
        :class:`~introspection_sdk.ValidationError` (400) when discovery
        fails.
        """
        payload = await self._http.request(
            "POST",
            "/v1/connectors/discover-oauth",
            json=ConnectorOAuthDiscoveryRequest(issuer=issuer).model_dump(
                mode="json"
            ),
        )
        return decode(ConnectorOAuthDiscoveryResponse, payload)

    async def get(self, connector_id: UUID) -> Connector:
        payload = await self._http.request(
            "GET",
            f"/v1/connectors/{connector_id}",
        )
        return decode(Connector, payload)

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
        policy_entities: builtins.list[PolicyEntity | dict[str, Any]]
        | None = None,
        client_secret: str | None = None,
        signing_secret: str | None = None,
        webhook_auth: WebhookAuth | str | None = None,
        rotate_signing_secret: bool = False,
    ) -> ConnectorSecretResponse:
        """Update a connector. Only provided fields change; an omitted
        ``client_secret`` / ``signing_secret`` stays as it is (write-only
        rotation, never a clear). ``policy_entities`` replaces the
        connector's Cedar entities.

        For a ``webhook`` connector, ``webhook_auth`` changes how callers
        authenticate and ``rotate_signing_secret=True`` issues a new
        secret, returned once as ``signing_secret`` on the response; the
        previous one is accepted until
        ``previous_signing_secret_expires_at`` (24 hours). Either on any
        other connector, or a ``client_secret`` / ``signing_secret`` on a
        webhook connector, is a 422."""
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
                policy_entities=policy_entities,
                client_secret=client_secret,
                signing_secret=signing_secret,
                webhook_auth=webhook_auth,
                rotate_signing_secret=rotate_signing_secret,
            ),
        )
        return decode(ConnectorSecretResponse, payload)

    async def delete(
        self, connector_id: UUID, *, project: str | UUID | None = None
    ) -> None:
        """Soft-delete a connector; its connections are revoked."""
        await self._http.request(
            "DELETE",
            f"/v1/connectors/{connector_id}",
            params=_project(project),
            expect="empty",
        )

    async def authorize(
        self,
        connector_id: UUID | None,
        *,
        integration_id: UUID | None = None,
        runtime: str | UUID | None = None,
        subject: ConnectionBrokerSubjectType | str | None = None,
        return_url: str | None = None,
        expires_in: int | None = None,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        app: str | None = None,
        allow_progressive_scopes: bool = False,
        binding: ConnectorAuthorizeBinding | dict[str, Any] | None = None,
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

        ``binding`` names the MCP endpoint (environment, Recipe MCP
        server id, https URL) the grant completes into. It requires
        ``runtime``; on a successful grant the control plane writes the
        endpoint binding in the same transaction as the connection, so
        the runtime is never authorized-but-unbound.

        ``integration_id`` installs an organization integration (Google
        Workspace, Microsoft 365) instead of a connector: pass ``None`` as
        ``connector_id``. It needs the ``integrations:write`` scope.
        """
        payload = await self._http.request(
            "POST",
            "/v1/oauth/connections/authorize",
            json=_authorize_body(
                connector_id=connector_id,
                integration_id=integration_id,
                runtime=runtime,
                subject=subject,
                return_url=return_url,
                expires_in=expires_in,
                identity=identity,
                app=app,
                allow_progressive_scopes=allow_progressive_scopes,
                binding=binding,
            ),
        )
        return decode(ConnectorAuthorization, payload)

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
        """Resolve a provider token, or a pending human-approval mission
        (``POST /v1/oauth/connections/token``)."""
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
