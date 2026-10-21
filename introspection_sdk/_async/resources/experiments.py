"""``client.experiments`` — CP CRUD + lifecycle + ``.run()`` returning a
:class:`Runner`.

Request documents for create/update are passed through to the Control Plane,
whose experiment schema is the source of truth.

``client.experiments`` is the :class:`Experiments` instance; calling
``client.experiments(id)`` returns an :class:`ExperimentHandle` with
``.run()``, ``.start()``, ``.end(...)``, and ``.cancel()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._errors import ValidationError
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.experiments import Experiment
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)


class Experiments:
    """CP ``/v1/experiments`` namespace.

    Also callable: ``client.experiments(id)`` returns an
    :class:`ExperimentHandle`.
    """

    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def __call__(self, experiment_id: UUID) -> ExperimentHandle:
        return ExperimentHandle(self, experiment_id=experiment_id)

    # --- reads --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime: str | UUID | None = None,
        environment: str | None = None,
        status: str | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> Pager[Experiment, Paginated[Experiment]]:
        """List experiments. Iterate the returned :class:`Pager` to stream
        every experiment across pages, or call ``.page()`` for the first
        page only."""

        def fetch(cursor: str | None) -> Paginated[Experiment]:
            params: dict[str, Any] = {
                "project": str(project) if project else None,
                "runtime": str(runtime) if runtime is not None else None,
                "environment": environment,
                "status": status,
                "limit": limit,
                "next": cursor,
            }
            payload = self._http.request(
                "GET", "/v1/experiments", params=params
            )
            return Paginated[Experiment].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(
        self, experiment_id: UUID, *, project: str | UUID | None = None
    ) -> Experiment:
        params: dict[str, Any] = {}
        if project:
            params["project"] = str(project)
        payload = self._http.request(
            "GET",
            f"/v1/experiments/{experiment_id}",
            params=params or None,
        )
        return Experiment.model_validate(payload)

    def create(
        self,
        document: Mapping[str, Any],
        *,
        project: str | UUID | None = None,
    ) -> Experiment:
        body = dict(document)
        if project is not None:
            if "project" in body and "project_id" in body:
                raise ValidationError(
                    "experiment document must not contain both project and project_id",
                    status_code=422,
                    code="conflicting_experiment_project",
                )
            supplied = body.get("project", body.get("project_id"))
            if supplied is not None and str(supplied) != str(project):
                raise ValidationError(
                    "experiment document project conflicts with project",
                    status_code=422,
                    code="conflicting_experiment_project",
                )
            body.pop("project_id", None)
            body["project"] = str(project)
        return Experiment.model_validate(
            self._http.request("POST", "/v1/experiments", json=body)
        )

    def update(
        self,
        experiment_id: UUID,
        document: Mapping[str, Any],
        *,
        project: str | UUID | None = None,
    ) -> Experiment:
        return Experiment.model_validate(
            self._http.request(
                "PATCH",
                f"/v1/experiments/{experiment_id}",
                params={
                    "project": str(project) if project is not None else None
                },
                json=dict(document),
            )
        )

    def delete(
        self,
        experiment_id: UUID,
        *,
        project: str | UUID | None = None,
    ) -> None:
        self._http.request(
            "DELETE",
            f"/v1/experiments/{experiment_id}",
            params={"project": str(project) if project is not None else None},
            expect="empty",
        )

    def _post_run(
        self,
        experiment_id: UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    def _start(self, experiment_id: UUID) -> Experiment:
        payload = self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/start"
        )
        return Experiment.model_validate(payload)

    def _end(self, experiment_id: UUID) -> Experiment:
        payload = self._http.request(
            "POST",
            f"/v1/experiments/{experiment_id}/end",
        )
        return Experiment.model_validate(payload)

    def _cancel(self, experiment_id: UUID) -> Experiment:
        payload = self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/cancel"
        )
        return Experiment.model_validate(payload)


class ExperimentHandle:
    """Handle for a specific experiment.

    Built by ``client.experiments(id)``.
    """

    def __init__(
        self,
        experiments: Experiments,
        *,
        experiment_id: UUID,
    ) -> None:
        self._experiments = experiments
        self._experiment_id = experiment_id

    @property
    def experiment_id(self) -> UUID:
        return self._experiment_id

    def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = 3600,
        scope: str | None = None,
    ) -> Runner:
        ident: RunnerIdentity | None
        if identity is None:
            ident = None
        elif isinstance(identity, RunnerIdentity):
            ident = identity
        else:
            ident = RunnerIdentity.model_validate(identity)
        call: RunCaller | None
        if caller is None:
            call = None
        elif isinstance(caller, RunCaller):
            call = caller
        else:
            call = RunCaller.model_validate(caller)
        options = RunRequest(
            identity=ident,
            caller=call,
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
        )
        eid = self._experiment_id

        def refresher() -> RunnerSpec:
            return self._experiments._post_run(eid, options)

        spec = refresher()
        return Runner(
            spec,
            refresher=refresher,
            additional_headers=self._experiments._additional_headers,
        )

    def start(self) -> Experiment:
        return self._experiments._start(self._experiment_id)

    def end(self) -> Experiment:
        return self._experiments._end(self._experiment_id)

    def cancel(self) -> Experiment:
        return self._experiments._cancel(self._experiment_id)


class AsyncExperiments:
    """Async twin of :class:`Experiments` (CP ``/v1/experiments``).

    Also callable: ``client.experiments(id)`` returns an
    :class:`AsyncExperimentHandle`.
    """

    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def __call__(self, experiment_id: UUID) -> AsyncExperimentHandle:
        return AsyncExperimentHandle(self, experiment_id=experiment_id)

    # --- reads --------------------------------------------------------

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime: str | UUID | None = None,
        environment: str | None = None,
        status: str | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> AsyncPager[Experiment, Paginated[Experiment]]:
        """List experiments. ``await`` the returned :class:`AsyncPager` for
        the first page, or ``async for`` it to stream every experiment across
        pages."""

        async def fetch(cursor: str | None) -> Paginated[Experiment]:
            params: dict[str, Any] = {
                "project": str(project) if project else None,
                "runtime": str(runtime) if runtime is not None else None,
                "environment": environment,
                "status": status,
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/experiments", params=params
            )
            return Paginated[Experiment].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(
        self, experiment_id: UUID, *, project: str | UUID | None = None
    ) -> Experiment:
        params: dict[str, Any] = {}
        if project:
            params["project"] = str(project)
        payload = await self._http.request(
            "GET",
            f"/v1/experiments/{experiment_id}",
            params=params or None,
        )
        return Experiment.model_validate(payload)

    async def create(
        self,
        document: Mapping[str, Any],
        *,
        project: str | UUID | None = None,
    ) -> Experiment:
        body = dict(document)
        if project is not None:
            if "project" in body and "project_id" in body:
                raise ValidationError(
                    "experiment document must not contain both project and project_id",
                    status_code=422,
                    code="conflicting_experiment_project",
                )
            supplied = body.get("project", body.get("project_id"))
            if supplied is not None and str(supplied) != str(project):
                raise ValidationError(
                    "experiment document project conflicts with project",
                    status_code=422,
                    code="conflicting_experiment_project",
                )
            body.pop("project_id", None)
            body["project"] = str(project)
        return Experiment.model_validate(
            await self._http.request("POST", "/v1/experiments", json=body)
        )

    async def update(
        self,
        experiment_id: UUID,
        document: Mapping[str, Any],
        *,
        project: str | UUID | None = None,
    ) -> Experiment:
        return Experiment.model_validate(
            await self._http.request(
                "PATCH",
                f"/v1/experiments/{experiment_id}",
                params={
                    "project": str(project) if project is not None else None
                },
                json=dict(document),
            )
        )

    async def delete(
        self,
        experiment_id: UUID,
        *,
        project: str | UUID | None = None,
    ) -> None:
        await self._http.request(
            "DELETE",
            f"/v1/experiments/{experiment_id}",
            params={"project": str(project) if project is not None else None},
            expect="empty",
        )

    async def _post_run(
        self,
        experiment_id: UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = await self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    async def _start(self, experiment_id: UUID) -> Experiment:
        payload = await self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/start"
        )
        return Experiment.model_validate(payload)

    async def _end(self, experiment_id: UUID) -> Experiment:
        payload = await self._http.request(
            "POST",
            f"/v1/experiments/{experiment_id}/end",
        )
        return Experiment.model_validate(payload)

    async def _cancel(self, experiment_id: UUID) -> Experiment:
        payload = await self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/cancel"
        )
        return Experiment.model_validate(payload)


class AsyncExperimentHandle:
    """Async twin of :class:`ExperimentHandle`.

    Built by ``client.experiments(id)``.
    """

    def __init__(
        self,
        experiments: AsyncExperiments,
        *,
        experiment_id: UUID,
    ) -> None:
        self._experiments = experiments
        self._experiment_id = experiment_id

    @property
    def experiment_id(self) -> UUID:
        return self._experiment_id

    async def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = 3600,
        scope: str | None = None,
    ) -> AsyncRunner:
        ident: RunnerIdentity | None
        if identity is None:
            ident = None
        elif isinstance(identity, RunnerIdentity):
            ident = identity
        else:
            ident = RunnerIdentity.model_validate(identity)
        call: RunCaller | None
        if caller is None:
            call = None
        elif isinstance(caller, RunCaller):
            call = caller
        else:
            call = RunCaller.model_validate(caller)
        options = RunRequest(
            identity=ident,
            caller=call,
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
        )
        eid = self._experiment_id

        async def refresher() -> RunnerSpec:
            return await self._experiments._post_run(eid, options)

        spec = await refresher()
        return AsyncRunner(
            spec,
            refresher=refresher,
            additional_headers=self._experiments._additional_headers,
        )

    async def start(self) -> Experiment:
        return await self._experiments._start(self._experiment_id)

    async def end(self) -> Experiment:
        return await self._experiments._end(self._experiment_id)

    async def cancel(self) -> Experiment:
        return await self._experiments._cancel(self._experiment_id)


__all__ = [
    "AsyncExperimentHandle",
    "AsyncExperiments",
    "ExperimentHandle",
    "Experiments",
]
