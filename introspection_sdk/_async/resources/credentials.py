"""Re-exported by :mod:`introspection_sdk.resources.credentials`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import SecretStr

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.lanes import Environment
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runtime_settings import (
    Credential,
    CredentialCreateRequest,
    CredentialUpdateRequest,
)


def _setting_list_params(
    *,
    project: str | UUID | None,
    runtime_id: UUID | None,
    runtime: str | None,
    environment: Environment | str | None,
    limit: int | None,
    next: str | None,
) -> dict[str, Any]:
    """Filters ``GET /v1/credentials`` and ``GET /v1/variables`` share."""
    return {
        **_project(project),
        "runtime_id": str(runtime_id) if runtime_id is not None else None,
        "runtime": runtime,
        "environment": str(environment) if environment is not None else None,
        "limit": limit,
        "next": next,
    }


def _credential_path(credential_id: UUID) -> str:
    return f"/v1/credentials/{credential_id}"


class AsyncCredentials(_AsyncResource):
    """CP ``/v1/credentials`` namespace: secrets a project's runtimes read,
    scoped to the project, a runtime group, a runtime and/or one lane.

    The secret is write-only: no read returns it. Needs an org credential;
    ``project`` (slug or id) names the project when the credential does not.
    """

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime_id: UUID | None = None,
        runtime: str | None = None,
        environment: Environment | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Credential, Paginated[Credential]]:
        """List credentials, across pages. ``runtime`` is a runtime slug."""
        return self._paginate(
            "/v1/credentials",
            Paginated[Credential],
            _setting_list_params(
                project=project,
                runtime_id=runtime_id,
                runtime=runtime,
                environment=environment,
                limit=limit,
                next=next,
            ),
        )

    async def get(
        self, credential_id: UUID, *, project: str | UUID | None = None
    ) -> Credential:
        return await self._call(
            "GET",
            _credential_path(credential_id),
            Credential,
            params=_project(project),
        )

    async def create(
        self,
        *,
        name: str,
        secret: str | SecretStr,
        project: str | UUID | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        environment: Environment | str | None = None,
    ) -> Credential:
        """Store a credential. With neither ``runtime_id`` nor
        ``runtime_group_id`` it is project-wide; ``environment=None`` applies
        to every lane."""
        body = _body(
            CredentialCreateRequest,
            {
                "name": name,
                "secret": secret,
                "runtime_id": runtime_id,
                "runtime_group_id": runtime_group_id,
                "environment": environment,
            },
        )
        return await self._call(
            "POST",
            "/v1/credentials",
            Credential,
            params=_project(project),
            json=body,
        )

    async def update(
        self,
        credential_id: UUID,
        *,
        project: str | UUID | None = None,
        name: str | None = None,
        secret: str | SecretStr | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        environment: Environment | str | None = None,
    ) -> Credential:
        """Only given fields change; pass ``secret`` to rotate it."""
        body = _body(
            CredentialUpdateRequest,
            {
                "name": name,
                "secret": secret,
                "runtime_id": runtime_id,
                "runtime_group_id": runtime_group_id,
                "environment": environment,
            },
        )
        return await self._call(
            "PATCH",
            _credential_path(credential_id),
            Credential,
            params=_project(project),
            json=body,
        )

    async def delete(
        self, credential_id: UUID, *, project: str | UUID | None = None
    ) -> None:
        await self._delete(_credential_path(credential_id), _project(project))
