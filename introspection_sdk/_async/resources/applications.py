"""Re-exported by :mod:`introspection_sdk.resources.applications`."""

from __future__ import annotations

import builtins
from uuid import UUID

from pydantic import SecretStr, TypeAdapter

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.applications import (
    Application,
    ApplicationCreateRequest,
    ApplicationIdp,
    ApplicationIdpCreateRequest,
    ApplicationIdpProvider,
    ApplicationKey,
    ApplicationSecret,
    ApplicationSecretCreateRequest,
    ApplicationType,
    ApplicationUpdateRequest,
)
from introspection_sdk.schemas.lanes import Environment
from introspection_sdk.schemas.pagination import Paginated

_KEYS = TypeAdapter(list[ApplicationKey])


def _app_path(application_id: UUID) -> str:
    return f"/v1/applications/{application_id}"


class AsyncApplicationIdps(_AsyncResource):
    """CP ``/v1/applications/{id}/idps``: the identity providers an
    Application brokers, whose users sign in as customer members."""

    def list(
        self,
        application_id: UUID,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[ApplicationIdp, Paginated[ApplicationIdp]]:
        """List an Application's identity providers, across pages."""
        return self._paginate(
            f"{_app_path(application_id)}/idps",
            Paginated[ApplicationIdp],
            {"limit": limit, "next": next},
        )

    async def create(
        self,
        application_id: UUID,
        *,
        idp_provider: ApplicationIdpProvider | str | None = None,
        issuer: str | None = None,
        client_id: str | None = None,
        client_secret: str | SecretStr | None = None,
        scopes: builtins.list[str] | None = None,
        audience_client_id: str | None = None,
    ) -> ApplicationIdp:
        """Attach an identity provider (``idp_provider`` defaults to
        ``generic``). ``client_secret`` is write-only."""
        body = _body(
            ApplicationIdpCreateRequest,
            {
                "idp_provider": idp_provider,
                "issuer": issuer,
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": scopes,
                "audience_client_id": audience_client_id,
            },
        )
        return await self._call(
            "POST",
            f"{_app_path(application_id)}/idps",
            ApplicationIdp,
            json=body,
        )

    async def delete(self, application_id: UUID, idp_id: UUID) -> None:
        await self._delete(f"{_app_path(application_id)}/idps/{idp_id}")


class AsyncApplicationSecrets(_AsyncResource):
    """CP ``/v1/applications/{id}/secrets``: a confidential Application's
    client secrets."""

    def list(
        self,
        application_id: UUID,
        *,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[ApplicationSecret, Paginated[ApplicationSecret]]:
        """List an Application's client secrets (never the plaintext)."""
        return self._paginate(
            f"{_app_path(application_id)}/secrets",
            Paginated[ApplicationSecret],
            {"limit": limit, "next": next},
        )

    async def create(
        self, application_id: UUID, *, name: str | None = None
    ) -> ApplicationSecret:
        """Mint a client secret. Its plaintext is
        :attr:`ApplicationSecret.secret` (a ``SecretStr``) on this response
        only."""
        return await self._call(
            "POST",
            f"{_app_path(application_id)}/secrets",
            ApplicationSecret,
            json=_body(ApplicationSecretCreateRequest, {"name": name}),
        )

    async def delete(
        self,
        application_id: UUID,
        secret_id: UUID,
        *,
        expires_in: int | None = None,
    ) -> None:
        """Disable a secret now, or after ``expires_in`` seconds for a
        rotation."""
        await self._delete(
            f"{_app_path(application_id)}/secrets/{secret_id}",
            {"expires_in": expires_in},
        )


class AsyncApplicationKeys(_AsyncResource):
    """CP ``/v1/applications/{id}/keys``: a ``jwks`` Application's signing
    keys."""

    async def list(
        self, application_id: UUID
    ) -> builtins.list[ApplicationKey]:
        """Every signing key (the route is not paginated)."""
        payload = await self._http.request(
            "GET", f"{_app_path(application_id)}/keys"
        )
        return _KEYS.validate_python(payload)

    async def create(self, application_id: UUID) -> ApplicationKey:
        """Mint a key pair; the API keeps the private half."""
        return await self._call(
            "POST", f"{_app_path(application_id)}/keys", ApplicationKey
        )

    async def delete(self, application_id: UUID, key_id: UUID) -> None:
        await self._delete(f"{_app_path(application_id)}/keys/{key_id}")


class AsyncApplications(_AsyncResource):
    """CP ``/v1/applications`` namespace: a project's OAuth clients, with
    ``idps``, ``secrets`` and ``keys`` under each.

    Needs an org credential; ``project`` (slug or id) names the project
    when the credential does not.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        super().__init__(http)
        self.idps = AsyncApplicationIdps(http)
        self.secrets = AsyncApplicationSecrets(http)
        self.keys = AsyncApplicationKeys(http)

    def list(
        self,
        *,
        project: str | UUID | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Application, Paginated[Application]]:
        """List the project's Applications, across pages."""
        return self._paginate(
            "/v1/applications",
            Paginated[Application],
            {**_project(project), "limit": limit, "next": next},
        )

    async def get(
        self, application_id: UUID, *, project: str | UUID | None = None
    ) -> Application:
        return await self._call(
            "GET",
            _app_path(application_id),
            Application,
            params=_project(project),
        )

    async def create(
        self,
        *,
        name: str,
        application_type: ApplicationType | str,
        project: str | UUID | None = None,
        environment: Environment | str | None = None,
        redirect_uris: builtins.list[str] | None = None,
        allowed_origins: builtins.list[str] | None = None,
        allowed_scopes: builtins.list[str] | None = None,
        agent_member_id: UUID | None = None,
    ) -> Application:
        """Register an OAuth client. Every plan may create a
        ``service_account``; the browser and federated types are
        plan-gated."""
        body = _body(
            ApplicationCreateRequest,
            {
                "name": name,
                "application_type": application_type,
                "environment": environment,
                "redirect_uris": redirect_uris,
                "allowed_origins": allowed_origins,
                "allowed_scopes": allowed_scopes,
                "agent_member_id": agent_member_id,
            },
        )
        return await self._call(
            "POST",
            "/v1/applications",
            Application,
            params=_project(project),
            json=body,
        )

    async def update(
        self,
        application_id: UUID,
        *,
        project: str | UUID | None = None,
        name: str | None = None,
        redirect_uris: builtins.list[str] | None = None,
        allowed_origins: builtins.list[str] | None = None,
        allowed_scopes: builtins.list[str] | None = None,
        agent_member_id: UUID | None = None,
    ) -> Application:
        """Only given fields change; a list replaces the whole value."""
        body = _body(
            ApplicationUpdateRequest,
            {
                "name": name,
                "redirect_uris": redirect_uris,
                "allowed_origins": allowed_origins,
                "allowed_scopes": allowed_scopes,
                "agent_member_id": agent_member_id,
            },
        )
        return await self._call(
            "PATCH",
            _app_path(application_id),
            Application,
            params=_project(project),
            json=body,
        )

    async def delete(
        self, application_id: UUID, *, project: str | UUID | None = None
    ) -> None:
        await self._delete(_app_path(application_id), _project(project))
