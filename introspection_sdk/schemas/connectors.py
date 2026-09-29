"""Pydantic mirrors of CP `/v1/connectors` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.

``client_secret`` and ``signing_secret`` are **write-only**: the API
accepts them on create and update and never returns them, so the read
models here deliberately have no such fields. Omitting them on update
means "unchanged", not "clear".
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from introspection_sdk.schemas.runner import RunnerIdentity


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConnectorAuthMode(StrEnum):
    """How a connector acquires credentials for its provider."""

    STATIC = "static"
    OAUTH_STORED = "oauth_stored"
    CLIENT_CREDENTIALS = "client_credentials"
    IDENTITY_ASSERTION = "identity_assertion"
    FEDERATED_EXCHANGE = "federated_exchange"
    PERSON_AUTHORIZED = "person_authorized"


class ConnectorStatus(StrEnum):
    """Lifecycle status of a connector."""

    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"


class ConnectionStatus(StrEnum):
    """Lifecycle status of a connection."""

    PENDING_AUTHORIZATION = "pending_authorization"
    ACTIVE = "active"
    REFRESH_FAILED = "refresh_failed"
    REVOKED = "revoked"


class ConnectionSubjectType(StrEnum):
    """Who a connection acts as against the provider."""

    APP = "app"
    USER = "user"
    FEDERATED = "federated"
    PERSON = "person"
    WORKSPACE = "workspace"


class ConnectionCreateSubjectType(StrEnum):
    """Subjects accepted by registered connection creation."""

    APP = "app"
    USER = "user"


class ConnectionBrokerSubjectType(StrEnum):
    """Subjects accepted by authorize and token-broker operations."""

    APP = "app"
    USER = "user"
    PERSON = "person"


class ConnectorPersonServerMode(StrEnum):
    """How a person-authorized connector reaches its Person Server."""

    MANAGED = "managed"
    BYO = "byo"
    DISCOVERED = "discovered"


class ConnectorApprovalPolicy(StrEnum):
    """Who approves a person-authorized connector's actions."""

    HUMAN = "human"
    JUDGE_ADVISES_HUMAN = "judge_advises_human"
    JUDGE_AUTO_WITHIN_ENVELOPE = "judge_auto_within_envelope"


class Connector(_ApiModel):
    """A connector (`/v1/connectors`) — a provider integration owned by a
    project.

    ``client_secret`` / ``signing_secret`` are write-only and never
    appear here. ``requires_runtime`` is server-derived: when ``True``,
    :meth:`~introspection_sdk.resources.connectors.Connectors.authorize`
    must name a ``runtime`` — read this field, never hardcode a provider
    list.
    """

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    slug: str
    name: str
    provider: str
    auth_mode: ConnectorAuthMode
    environment: str
    agent_member_id: UUID | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    scopes: list[str] = []
    api_hosts: list[str] = []
    client_id: str | None = None
    person_server_mode: ConnectorPersonServerMode | None = None
    person_server_url: str | None = None
    approval_policy: ConnectorApprovalPolicy = ConnectorApprovalPolicy.HUMAN
    application_id: UUID | None = None
    assertion_audience: str | None = None
    webhook_url: str | None = None
    status: ConnectorStatus = ConnectorStatus.PENDING
    created_by_member_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    requires_runtime: bool = False


class Connection(_ApiModel):
    """A connection — one authorized subject under a connector.

    Access/refresh tokens are never serialized by the API and are not
    modeled here.
    """

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime
    connector_id: UUID
    member_id: UUID | None = None
    """``None`` = org-owned (app subject); for a Slack workspace install
    this points at the workspace customer member."""
    created_by_member_id: UUID | None = None
    """The member who performed the grant, as distinct from ``member_id``
    (whose credential this is). For ``app`` and ``workspace`` subjects those
    are never the same principal. ``None`` for grants made before the
    column existed."""
    runtime_group_id: UUID | None = None
    """Runtime group answering this connection's channels."""
    subject_type: ConnectionSubjectType = ConnectionSubjectType.APP
    scopes_granted: list[str] = []
    status: ConnectionStatus = ConnectionStatus.ACTIVE
    token_expires_at: datetime | None = None
    provider_app: str | None = None
    """Application slug within a multi-application provider (Pipedream);
    ``None`` otherwise."""
    provider_account_id: str | None = None
    """The provider's own identifier for the connected account."""


class ConnectorCreateRequest(_ApiModel):
    """Create a connector (``POST /v1/connectors`` body).

    ``client_secret`` and ``signing_secret`` are write-only: accepted
    here, absent from every response. ``slug`` is derived from ``name``
    when omitted and is unique per project: a repeat create with the same
    slug replaces the live connector's configuration (name, environment,
    endpoints, scopes, api hosts, client id, metadata, ...) and keeps its
    ``provider``, ``auth_mode`` and stored secrets. ``issuer`` drives
    OAuth endpoint discovery (and, where the provider supports it, client
    registration) and is not persisted.
    """

    name: str
    provider: str
    auth_mode: ConnectorAuthMode
    slug: str | None = None
    environment: str | None = None
    agent_member_id: UUID | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    scopes: list[str] | None = None
    api_hosts: list[str] | None = None
    client_id: str | None = None
    client_secret: str | None = None
    signing_secret: str | None = None
    metadata: dict[str, Any] | None = None
    """Provider-specific settings. A ``pipedream`` connector requires
    ``provider_workspace_id`` — its Pipedream Connect project id
    (``proj_...``); ``provider_environment`` is derived from
    ``environment`` by the server and need not be sent."""
    issuer: str | None = None
    person_server_mode: ConnectorPersonServerMode | None = None
    person_server_url: str | None = None
    approval_policy: ConnectorApprovalPolicy | None = None
    application_id: UUID | None = None
    assertion_audience: str | None = None
    webhook_url: str | None = None


class ConnectorUpdateRequest(_ApiModel):
    """Update a connector (``PATCH /v1/connectors/{id}`` body).

    Only these fields are mutable; only provided fields change. The
    write-only secrets (``client_secret`` / ``signing_secret``) rotate
    when provided — omitted means "unchanged", not "clear".
    """

    name: str | None = None
    agent_member_id: UUID | None = None
    scopes: list[str] | None = None
    api_hosts: list[str] | None = None
    status: ConnectorStatus | None = None
    metadata: dict[str, Any] | None = None
    webhook_url: str | None = None
    client_secret: str | None = None
    signing_secret: str | None = None


class ConnectionCreateRequest(_ApiModel):
    """Register a connection with a caller-supplied token
    (``POST /v1/connectors/{connector_id}/connections`` body).

    ``access_token`` / ``refresh_token`` are write-only: stored
    encrypted server-side and never returned on any read.
    """

    access_token: str
    subject_type: ConnectionCreateSubjectType | None = None
    scopes_granted: list[str] | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


class ConnectorAuthorizeBinding(_ApiModel):
    """The MCP endpoint binding an authorize completes into.

    On a successful grant the control plane writes this endpoint binding
    in the same transaction as the connection, so the runtime is never
    authorized-but-unbound. Requires ``runtime`` on the authorize request.
    Non-secret: the provider token stays on the connection and is
    injected at the egress, so ``headers`` cannot set ``Authorization``.
    """

    environment: str
    """Runtime environment lane (``development`` / ``staging`` /
    ``production``) the endpoint belongs to."""
    mcp_server_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$",
    )
    """The Recipe MCP server id this connector backs
    (``package.json#pi.mcp.servers[].id``)."""
    url: str = Field(min_length=1, max_length=1024)
    """Streamable-HTTP MCP resource URL (https)."""
    name: str | None = Field(default=None, max_length=255)
    """Display label; defaults to ``mcp_server_id``."""
    headers: dict[str, str] | None = None
    """Extra non-``Authorization`` headers sent alongside the connection
    token."""


class ConnectorAuthorizeRequest(_ApiModel):
    """Mint a consent URL (``POST /v1/oauth/connections/authorize`` body).

    ``runtime`` (slug or runtime group id) is required by the server
    when the connector's ``requires_runtime`` is ``True`` — it names the
    agent that replies.
    """

    connector_id: UUID
    app: str | None = None
    allow_progressive_scopes: bool = False
    runtime: str | None = None
    subject: ConnectionBrokerSubjectType | None = None
    return_url: str | None = None
    expires_in: int | None = None
    identity: RunnerIdentity | None = None
    """The end customer this grant is being made for, asserted by the
    caller. Its ``user_id`` resolves a ``customer`` member recorded as the
    connection's ``created_by_member_id``, so a partner can associate the
    connection with their own caller rather than the agent member that made
    the API call. Omit to attribute the grant to the authenticated
    principal."""
    binding: ConnectorAuthorizeBinding | None = None
    """MCP endpoint binding written with the grant; requires ``runtime``."""


class ConnectorAuthorization(_ApiModel):
    """The minted consent link (authorize response).

    Each call writes a fresh single-use ``state`` into the URL: two
    calls give two different URLs, so never cache this response.
    """

    authorize_url: str
    expires_in: int
    expires_at: datetime


class ConnectorApp(_ApiModel):
    """An application listing — from a connector's provider catalogue, or
    from the open MCP registry a custom connector picks from."""

    slug: str
    name: str
    icon_url: str | None = None
    description: str | None = None
    auth_type: str | None = None
    mcp_url: str | None = None
    """The listing's MCP server, where it has one."""
    docs_url: str | None = None
    """The vendor's documentation for this server, where known."""


class ConnectorOAuthClientRegistration(StrEnum):
    """How the platform identified itself to a custom OAuth provider."""

    CLIENT_ID_METADATA_DOCUMENT = "client_id_metadata_document"
    DYNAMIC = "dynamic"
    PRE_REGISTERED = "pre_registered"


class ConnectorOAuthDiscoveryRequest(_ApiModel):
    """Resolve OAuth metadata (``POST /v1/connectors/discover-oauth``
    body). ``issuer`` is an authorization-server issuer URL, or an MCP
    server URL whose RFC 9728 metadata names its authorization server."""

    issuer: str = Field(min_length=1)


class ConnectorOAuthDiscoveryResponse(_ApiModel):
    """What OAuth discovery learned about a provider.

    ``client_id`` / ``client_secret`` are set when the control plane
    obtained a client automatically (``client_registration``); pass them
    to ``create`` so a second client is not registered. ``redirect_uri``
    is the exact callback a hand-registered client must be given.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    token_endpoint_auth_methods_supported: list[str] = Field(
        default_factory=list
    )
    code_challenge_methods_supported: list[str] = Field(default_factory=list)
    scopes_supported: list[str] = Field(default_factory=list)
    client_id_metadata_document_supported: bool = False
    resource: str | None = None
    redirect_uri: str
    client_id: str | None = None
    client_secret: str | None = None
    client_registration: ConnectorOAuthClientRegistration | None = None


class ConnectionMissionConstraints(_ApiModel):
    """Deterministic, non-PII envelope for a person-authorized action."""

    host: str | None = None
    resource: str | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    payload_binding: str | None = None


class ConnectionTokenRequest(_ApiModel):
    connector_id: UUID
    subject: ConnectionBrokerSubjectType | None = None
    action: str | None = None
    requested_permissions: ConnectionMissionConstraints | None = None


class ConnectionToken(_ApiModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class ConnectionAuthorizationPending(_ApiModel):
    status: Literal["authorization_pending"]
    mission_id: UUID
    approval_url: str


ConnectionTokenResult = ConnectionToken | ConnectionAuthorizationPending


__all__ = [
    "Connection",
    "ConnectionAuthorizationPending",
    "ConnectionBrokerSubjectType",
    "ConnectionCreateRequest",
    "ConnectionCreateSubjectType",
    "ConnectionMissionConstraints",
    "ConnectionStatus",
    "ConnectionSubjectType",
    "ConnectionToken",
    "ConnectionTokenRequest",
    "ConnectionTokenResult",
    "Connector",
    "ConnectorApprovalPolicy",
    "ConnectorApp",
    "ConnectorAuthMode",
    "ConnectorAuthorization",
    "ConnectorAuthorizeBinding",
    "ConnectorAuthorizeRequest",
    "ConnectorCreateRequest",
    "ConnectorOAuthClientRegistration",
    "ConnectorOAuthDiscoveryRequest",
    "ConnectorOAuthDiscoveryResponse",
    "ConnectorPersonServerMode",
    "ConnectorStatus",
    "ConnectorUpdateRequest",
]
