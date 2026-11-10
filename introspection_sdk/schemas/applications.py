"""Pydantic mirrors of CP ``/v1/applications`` request/response models.

An Application is an OAuth client of a project. Under it live the identity
providers it brokers, its client secrets and its signing keys. A client
secret's plaintext rides only the create response, and an IdP's
``client_secret`` is write-only in practice; both are
:class:`~pydantic.SecretStr`, so neither prints.

Response models ignore unknown fields and keep their enums open (a value
this SDK does not know decodes as a plain ``str``); request bodies forbid
unknown fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from introspection_sdk.schemas._secrets import WireSecret
from introspection_sdk.schemas.lanes import Environment, OpenEnvironment


class _ApiModel(BaseModel):
    """Base of the response models; a field the API adds is ignored."""


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationType(StrEnum):
    NATIVE = "native"
    SPA = "spa"
    JWKS = "jwks"
    SERVICE_ACCOUNT = "service_account"


class ApplicationGrant(StrEnum):
    AUTHORIZATION_CODE = "authorization_code"
    REFRESH_TOKEN = "refresh_token"
    CLIENT_CREDENTIALS = "client_credentials"
    DEVICE_CODE = "device_code"
    EMAIL_CODE = "email_code"


OpenApplicationType = Annotated[
    ApplicationType | str, Field(union_mode="left_to_right")
]
OpenApplicationGrant = Annotated[
    ApplicationGrant | str, Field(union_mode="left_to_right")
]


class Application(_ApiModel):
    """An OAuth client registered in a project."""

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str
    application_type: OpenApplicationType
    environment: OpenEnvironment = Environment.PRODUCTION
    redirect_uris: list[str] = []
    allowed_origins: list[str] = []
    allowed_scopes: list[str] = []
    client_id: str
    agent_member_id: UUID | None = None
    allowed_grants: list[OpenApplicationGrant] = []
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by_member_id: UUID


class ApplicationCreateRequest(_Request):
    """Body of ``POST /v1/applications``."""

    name: str
    application_type: ApplicationType
    environment: Environment | None = None
    redirect_uris: list[str] | None = None
    allowed_origins: list[str] | None = None
    allowed_scopes: list[str] | None = None
    agent_member_id: UUID | None = None


class ApplicationUpdateRequest(_Request):
    """Body of ``PATCH /v1/applications/{id}``. A list replaces the whole
    value."""

    name: str | None = None
    redirect_uris: list[str] | None = None
    allowed_origins: list[str] | None = None
    allowed_scopes: list[str] | None = None
    agent_member_id: UUID | None = None


class ApplicationIdpProvider(StrEnum):
    AUTH0 = "auth0"
    OKTA = "okta"
    SUPABASE = "supabase"
    NEON = "neon"
    GENERIC = "generic"
    ZITADEL = "zitadel"


class ApplicationIdpStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"


OpenApplicationIdpProvider = Annotated[
    ApplicationIdpProvider | str, Field(union_mode="left_to_right")
]
OpenApplicationIdpStatus = Annotated[
    ApplicationIdpStatus | str, Field(union_mode="left_to_right")
]


class ApplicationIdp(_ApiModel):
    """An identity provider brokered into an Application, whose users sign
    in as customer members."""

    id: UUID
    org_id: UUID
    application_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    idp_provider: OpenApplicationIdpProvider = ApplicationIdpProvider.GENERIC
    issuer: str
    client_id: str
    scopes: list[str] = []
    external_org_id: str | None = None
    external_idp_id: str | None = None
    audience_client_id: str | None = None
    status: OpenApplicationIdpStatus = ApplicationIdpStatus.PENDING
    error_message: str | None = None
    disabled_at: datetime | None = None
    client_secret: SecretStr | None = None
    is_active: bool


class ApplicationIdpCreateRequest(_Request):
    """Body of ``POST /v1/applications/{id}/idps``."""

    idp_provider: ApplicationIdpProvider | None = None
    """Defaults to ``generic`` server-side."""
    issuer: str | None = None
    client_id: str | None = None
    client_secret: WireSecret | None = None
    scopes: list[str] | None = None
    audience_client_id: str | None = None


class ApplicationSecretStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"


OpenApplicationSecretStatus = Annotated[
    ApplicationSecretStatus | str, Field(union_mode="left_to_right")
]


class ApplicationSecret(_ApiModel):
    """A client secret of a confidential Application. ``secret`` is set only
    on the create response."""

    id: UUID
    org_id: UUID
    application_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    secret_prefix: str
    secret_suffix: str
    name: str | None = None
    expires_at: datetime | None = None
    disabled_at: datetime | None = None
    last_used_at: datetime | None = None
    created_by_member_id: UUID
    secret: SecretStr | None = None
    status: OpenApplicationSecretStatus


class ApplicationSecretCreateRequest(_Request):
    """Body of ``POST /v1/applications/{id}/secrets``."""

    name: str | None = None


class ApplicationKey(_ApiModel):
    """A signing key of a ``jwks`` Application: the public half, published
    at the Application's JWKS URL. The API keeps the private half."""

    id: UUID
    org_id: UUID
    application_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    kid: str
    algorithm: str
    public_key: str
    created_by_member_id: UUID | None = None


__all__ = [
    "Application",
    "ApplicationCreateRequest",
    "ApplicationGrant",
    "ApplicationIdp",
    "ApplicationIdpCreateRequest",
    "ApplicationIdpProvider",
    "ApplicationIdpStatus",
    "ApplicationKey",
    "ApplicationSecret",
    "ApplicationSecretCreateRequest",
    "ApplicationSecretStatus",
    "ApplicationType",
    "ApplicationUpdateRequest",
    "OpenApplicationGrant",
    "OpenApplicationIdpProvider",
    "OpenApplicationIdpStatus",
    "OpenApplicationSecretStatus",
    "OpenApplicationType",
]
