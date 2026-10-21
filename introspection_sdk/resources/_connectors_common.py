"""Code shared by the sync and async twins in :mod:`introspection_sdk.resources.connectors`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from introspection_sdk.schemas.connectors import (
    ConnectionAuthorizationPending,
    ConnectionBrokerSubjectType,
    ConnectionCreateRequest,
    ConnectionCreateSubjectType,
    ConnectionMissionConstraints,
    ConnectionToken,
    ConnectionTokenRequest,
    ConnectionTokenResult,
    ConnectorAuthMode,
    ConnectorAuthorizeBinding,
    ConnectorAuthorizeRequest,
    ConnectorCreateRequest,
    ConnectorStatus,
    ConnectorUpdateRequest,
    PolicyEntity,
)
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
    app: str | None,
    allow_progressive_scopes: bool,
    binding: ConnectorAuthorizeBinding | dict[str, Any] | None,
) -> dict[str, Any]:
    return ConnectorAuthorizeRequest.model_validate(
        {
            "connector_id": connector_id,
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
