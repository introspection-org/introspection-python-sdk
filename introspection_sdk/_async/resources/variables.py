"""Re-exported by :mod:`introspection_sdk.resources.variables`."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk._async.resources._crud import (
    _AsyncResource,
    _body,
    _project,
)
from introspection_sdk._async.resources.credentials import (
    _setting_list_params,
)
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.lanes import Environment
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runtime_settings import (
    Variable,
    VariableCreateRequest,
    VariableKind,
    VariableUpdateRequest,
)


def _variable_path(variable_id: UUID) -> str:
    return f"/v1/variables/{variable_id}"


class AsyncVariables(_AsyncResource):
    """CP ``/v1/variables`` namespace: environment variables a project's
    runtimes read, scoped like credentials.

    The API has no read-one route. Needs an org credential; ``project``
    (slug or id) names the project when the credential does not.
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
    ) -> AsyncPager[Variable, Paginated[Variable]]:
        """List variables, across pages. ``runtime`` is a runtime slug."""
        return self._paginate(
            "/v1/variables",
            Paginated[Variable],
            _setting_list_params(
                project=project,
                runtime_id=runtime_id,
                runtime=runtime,
                environment=environment,
                limit=limit,
                next=next,
            ),
        )

    async def create(
        self,
        *,
        name: str,
        value: str | None = None,
        kind: VariableKind | str | None = None,
        project: str | UUID | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        environment: Environment | str | None = None,
    ) -> Variable:
        """Set a variable. ``kind`` defaults to ``value``; a ``credential``
        variable's ``value`` names a credential."""
        fields = {"name": name, "kind": kind, "value": value}
        return await self._call(
            "POST",
            "/v1/variables",
            Variable,
            params=_project(project),
            json=_body(
                VariableCreateRequest,
                {
                    **fields,
                    "runtime_id": runtime_id,
                    "runtime_group_id": runtime_group_id,
                    "environment": environment,
                },
            ),
        )

    async def update(
        self,
        variable_id: UUID,
        *,
        project: str | UUID | None = None,
        name: str | None = None,
        value: str | None = None,
        kind: VariableKind | str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        environment: Environment | str | None = None,
    ) -> Variable:
        """Only given fields change."""
        fields = {"name": name, "kind": kind, "value": value}
        return await self._call(
            "PATCH",
            _variable_path(variable_id),
            Variable,
            params=_project(project),
            json=_body(
                VariableUpdateRequest,
                {
                    **fields,
                    "runtime_id": runtime_id,
                    "runtime_group_id": runtime_group_id,
                    "environment": environment,
                },
            ),
        )

    async def delete(
        self, variable_id: UUID, *, project: str | UUID | None = None
    ) -> None:
        await self._delete(_variable_path(variable_id), _project(project))
