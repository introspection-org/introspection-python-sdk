"""Pydantic mirrors of CP `/v1/connectors` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.

``client_secret`` and ``signing_secret`` are **write-only**: the API
accepts them on create and update and never returns them, so the read
models here deliberately have no such fields. Omitting them on update
means "unchanged", not "clear". The one exception is a ``webhook``
connector's platform-generated ``signing_secret``, returned once in
:class:`ConnectorSecretResponse` on the update that issues it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from introspection_sdk.schemas.runner import RunnerIdentity


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConnectorAuthMode(StrEnum):
    """How a connector acquires credentials for its provider."""

    STATIC = "static"
    OAUTH_STORED = "oauth_stored"
    CLIENT_CREDENTIALS = "client_credentials"
    IDENTITY_ASSERTION = "identity_assertion"
    FEDERATED_EXCHANGE = "federated_exchange"
    PERSON_AUTHORIZED = "person_authorized"
    AAUTH = "aauth"


class WebhookSecretType(StrEnum):
    """How a caller proves it holds a ``webhook`` connector's secret."""

    STANDARD_WEBHOOKS = "standard_webhooks"
    """A Standard Webhooks signature (``webhook-id``,
    ``webhook-timestamp``, ``webhook-signature``) over the body, keyed by
    the secret (``whsec_...``)."""
    BEARER = "bearer"
    """``Authorization: Bearer <secret>`` (``whtok_...``)."""


OpenWebhookSecretType = Annotated[
    WebhookSecretType | str, Field(union_mode="left_to_right")
]


WEBHOOK_PROVIDER = "webhook"
"""The ``provider`` of an inbound-only connector the customer's own
systems call, at the control plane's ``/v1/webhooks/connectors/{id}``.
Its events start routines through a ``connector`` trigger."""


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


class ConnectionBrokerSubjectType(StrEnum):
    """Subjects accepted by authorize and token-broker operations."""

    APP = "app"
    USER = "user"
    PERSON = "person"


class EntityUid(ApiModel):
    """A Cedar entity reference, ``{"type": "Company", "id": "acme"}``."""

    type: str
    id: str


class PolicyEntity(ApiModel):
    """A Cedar entity a recipe's policies read, in Cedar's JSON entity
    format: e.g. a company and the seniority its business-class bookings
    need. The egress policy gate adds a connector's entities to every
    request it evaluates for that connector."""

    uid: EntityUid
    attrs: dict[str, Any] = Field(default_factory=dict)
    parents: list[EntityUid] = Field(default_factory=list)


class SigningSecretStatus(StrEnum):
    """Which of a ``webhook`` connector's two secret slots a secret is in."""

    CURRENT = "current"
    PREVIOUS = "previous"


class SigningSecret(ApiModel):
    """One secret a ``webhook`` connector accepts, without its material."""

    id: str
    """A fingerprint of the secret (its kid): the first 8 hex digits of
    its SHA-256. Revoke it with ``update(revoke_signing_secret=id)``."""
    type: OpenWebhookSecretType
    created_at: datetime | None = None
    status: SigningSecretStatus | str = Field(union_mode="left_to_right")
    """A status this SDK does not know decodes as a plain string."""


class Connector(ApiModel):
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
    person_server_url: str | None = None
    application_id: UUID | None = None
    assertion_audience: str | None = None
    policy_entities: list[PolicyEntity] | None = None
    webhook_url: str | None = None
    status: ConnectorStatus = ConnectorStatus.PENDING
    created_by_member_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    requires_runtime: bool = False
    signing_secrets: list[SigningSecret] | None = None
    """A ``webhook`` connector's accepted secrets (at most two), current
    first, described without their material; ``None`` for every other
    provider."""


class ConnectorSecretResponse(Connector):
    """An update response: a :class:`Connector`, plus a ``webhook``
    connector's secret the one time it is issued."""

    signing_secret: SecretStr | None = None
    """A ``webhook`` connector's new secret (``whsec_...`` or
    ``whtok_...``), on the ``rotate_signing_secret`` update only. Shown
    once: no read returns it. A
    :class:`~pydantic.SecretStr`, so it never prints; read it with
    ``.get_secret_value()``."""


class ConnectorCreateRequest(ApiModel):
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
    person_server_url: str | None = None
    """Person Server an ``aauth`` connector's grants go through; required
    for ``aauth``, together with ``application_id``."""
    application_id: UUID | None = None
    assertion_audience: str | None = None
    policy_entities: list[PolicyEntity] | None = None
    """Cedar entities the egress policy gate adds to this connector's
    requests."""
    webhook_url: str | None = None


class SigningSecretRotation(ApiModel):
    """``rotate_signing_secret`` naming the type of the secret it issues:
    how a ``webhook`` connector's first secret is issued."""

    type: WebhookSecretType


class ConnectorUpdateRequest(ApiModel):
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
    policy_entities: list[PolicyEntity] | None = None
    """Replaces the connector's Cedar entities; ``None`` leaves them
    untouched."""
    client_secret: str | None = None
    signing_secret: str | None = None
    """Not for a ``webhook`` connector, whose secrets the platform
    generates: issue one with ``rotate_signing_secret``."""
    rotate_signing_secret: bool | SigningSecretRotation | None = None
    """For a ``webhook`` connector only: issue a new secret, returned once
    in the response. The first names its type
    (:class:`SigningSecretRotation`); ``True`` rotates, keeping the
    current secret's type, and the old one stays valid as the previous
    secret until it is revoked. With two live, the server answers 409."""
    revoke_signing_secret: str | None = None
    """For a ``webhook`` connector only: the id (kid) of a live secret to
    stop accepting now. The current one only once no previous one is live
    (409). Not with ``rotate_signing_secret`` (422)."""


class ConnectorAuthorizeBinding(ApiModel):
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


class ConnectorAuthorizeRequest(ApiModel):
    """Mint a consent URL (``POST /v1/oauth/connections/authorize`` body).

    ``runtime`` (slug or runtime group id) is required by the server
    when the connector's ``requires_runtime`` is ``True`` — it names the
    agent that replies.
    """

    connector_id: UUID | None = None
    integration_id: UUID | None = None
    """An organization integration to install (Google Workspace,
    Microsoft 365) instead of a connector; needs ``integrations:write``."""
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


class ConnectorAuthorization(ApiModel):
    """The minted consent link (authorize response).

    Each call writes a fresh single-use ``state`` into the URL: two
    calls give two different URLs, so never cache this response.
    """

    authorize_url: str
    expires_in: int
    expires_at: datetime


class ConnectorApp(ApiModel):
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


class ConnectorOAuthDiscoveryRequest(ApiModel):
    """Resolve OAuth metadata (``POST /v1/connectors/discover-oauth``
    body). ``issuer`` is an authorization-server issuer URL, or an MCP
    server URL whose RFC 9728 metadata names its authorization server."""

    issuer: str = Field(min_length=1)


class ConnectorOAuthDiscoveryResponse(ApiModel):
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
    revocation_endpoint: str | None = None
    """RFC 7009 token revocation endpoint, if the provider advertises
    one."""


class ConnectionMissionConstraints(ApiModel):
    """Deterministic, non-PII envelope for a person-authorized action."""

    host: str | None = None
    resource: str | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    payload_binding: str | None = None


class ConnectionTokenRequest(ApiModel):
    connector_id: UUID
    subject: ConnectionBrokerSubjectType | None = None
    action: str | None = None
    requested_permissions: ConnectionMissionConstraints | None = None


class ConnectionToken(ApiModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class ConnectionAuthorizationPending(ApiModel):
    status: Literal["authorization_pending"]
    mission_id: UUID
    approval_url: str


ConnectionTokenResult = ConnectionToken | ConnectionAuthorizationPending


class ConnectorAppList(ApiModel):
    """The envelope of an app-catalogue search; the SDK returns its apps."""

    data: list[ConnectorApp] = []


__all__ = [
    "ConnectionAuthorizationPending",
    "ConnectionBrokerSubjectType",
    "ConnectionMissionConstraints",
    "ConnectionStatus",
    "ConnectionSubjectType",
    "ConnectionToken",
    "ConnectionTokenRequest",
    "ConnectionTokenResult",
    "Connector",
    "ConnectorApp",
    "ConnectorAuthMode",
    "ConnectorAuthorization",
    "ConnectorAuthorizeBinding",
    "ConnectorAuthorizeRequest",
    "ConnectorCreateRequest",
    "ConnectorOAuthClientRegistration",
    "ConnectorOAuthDiscoveryRequest",
    "ConnectorOAuthDiscoveryResponse",
    "ConnectorSecretResponse",
    "ConnectorStatus",
    "ConnectorUpdateRequest",
    "EntityUid",
    "PolicyEntity",
    "OpenWebhookSecretType",
    "SigningSecret",
    "SigningSecretRotation",
    "SigningSecretStatus",
    "WEBHOOK_PROVIDER",
    "WebhookSecretType",
]
