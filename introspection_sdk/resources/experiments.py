"""Experiment runner creation. Experiment management belongs elsewhere."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)


class _Experiments:
    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def handle(self, experiment_id: UUID) -> ExperimentHandle:
        return ExperimentHandle(self, experiment_id=experiment_id)

    def _post_run(
        self, experiment_id: UUID, options: RunRequest
    ) -> RunnerSpec:
        payload = self._http.request(
            "POST",
            f"/v1/experiments/{experiment_id}/run",
            json=options.model_dump(exclude_none=True, mode="json"),
        )
        return RunnerSpec.model_validate(payload)


class ExperimentHandle:
    """Open runners for one existing experiment."""

    def __init__(
        self, experiments: _Experiments, *, experiment_id: UUID
    ) -> None:
        self._experiments = experiments
        self._experiment_id = experiment_id

    def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = 3600,
        scope: str | None = None,
    ) -> Runner:
        options = RunRequest(
            identity=(
                identity
                if isinstance(identity, RunnerIdentity) or identity is None
                else RunnerIdentity.model_validate(identity)
            ),
            caller=(
                caller
                if isinstance(caller, RunCaller) or caller is None
                else RunCaller.model_validate(caller)
            ),
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
        )

        def refresher() -> RunnerSpec:
            return self._experiments._post_run(self._experiment_id, options)

        return Runner(
            refresher(),
            refresher=refresher,
            additional_headers=self._experiments._additional_headers,
        )


class _AsyncExperiments:
    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def handle(self, experiment_id: UUID) -> AsyncExperimentHandle:
        return AsyncExperimentHandle(self, experiment_id=experiment_id)

    async def _post_run(
        self, experiment_id: UUID, options: RunRequest
    ) -> RunnerSpec:
        payload = await self._http.request(
            "POST",
            f"/v1/experiments/{experiment_id}/run",
            json=options.model_dump(exclude_none=True, mode="json"),
        )
        return RunnerSpec.model_validate(payload)


class AsyncExperimentHandle:
    """Async experiment runner opener."""

    def __init__(
        self, experiments: _AsyncExperiments, *, experiment_id: UUID
    ) -> None:
        self._experiments = experiments
        self._experiment_id = experiment_id

    async def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = 3600,
        scope: str | None = None,
    ) -> AsyncRunner:
        options = RunRequest(
            identity=(
                identity
                if isinstance(identity, RunnerIdentity) or identity is None
                else RunnerIdentity.model_validate(identity)
            ),
            caller=(
                caller
                if isinstance(caller, RunCaller) or caller is None
                else RunCaller.model_validate(caller)
            ),
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
        )

        async def refresher() -> RunnerSpec:
            return await self._experiments._post_run(
                self._experiment_id, options
            )

        return AsyncRunner(
            await refresher(),
            refresher=refresher,
            additional_headers=self._experiments._additional_headers,
        )


__all__ = ["AsyncExperimentHandle", "ExperimentHandle"]
