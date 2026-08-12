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


class ConnectorCreateRequest(_ApiModel):
    """Create a connector (``POST /v1/connectors`` body).

    ``client_secret`` and ``signing_secret`` are write-only: accepted
    here, absent from every response. ``slug`` is derived from ``name``
    when omitted, and create is idempotent on it. ``issuer`` drives
    OAuth endpoint discovery and is not persisted.
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


class ConnectorAuthorizeRequest(_ApiModel):
    """Mint a consent URL (``POST /v1/oauth/connections/authorize`` body).

    ``runtime`` (slug or runtime group id) is required by the server
    when the connector's ``requires_runtime`` is ``True`` — it names the
    agent that replies.
    """

    connector_id: UUID
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


class ConnectorAuthorization(_ApiModel):
    """The minted consent link (authorize response).

    Each call writes a fresh single-use ``state`` into the URL: two
    calls give two different URLs, so never cache this response.
    """

    authorize_url: str
    expires_in: int
    expires_at: datetime


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
    "ConnectorAuthMode",
    "ConnectorAuthorization",
    "ConnectorAuthorizeRequest",
    "ConnectorCreateRequest",
    "ConnectorPersonServerMode",
    "ConnectorStatus",
    "ConnectorUpdateRequest",
]
