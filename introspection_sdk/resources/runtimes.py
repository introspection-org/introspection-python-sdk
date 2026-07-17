"""Runtime runner creation. Runtime management belongs to the CLI/frontend."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)


class _ResolvedRuntime(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID


class _Runtimes:
    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def handle(self, runtime: str | UUID) -> RuntimeHandle:
        return RuntimeHandle(self, runtime=runtime)

    def _resolve(self, runtime: str | UUID) -> UUID:
        payload = self._http.request(
            "GET",
            "/v1/runtimes",
            params={"runtime": str(runtime), "limit": 2},
        )
        records = payload.get("records", [])
        if not records:
            raise LookupError(f"No runtime {runtime!r}")
        if len(records) > 1:
            raise LookupError(
                f"Ambiguous runtime {runtime!r}: {len(records)} matches"
            )
        return _ResolvedRuntime.model_validate(records[0]).id

    def _post_run(self, runtime_id: UUID, options: RunRequest) -> RunnerSpec:
        payload = self._http.request(
            "POST",
            f"/v1/runtimes/{runtime_id}/run",
            json=options.model_dump(exclude_none=True, mode="json"),
        )
        return RunnerSpec.model_validate(payload)


class RuntimeHandle:
    """Open runners for one configured runtime group slug or id."""

    def __init__(self, runtimes: _Runtimes, *, runtime: str | UUID) -> None:
        self._runtimes = runtimes
        self._runtime = runtime
        self._resolved_id: UUID | None = None

    def _resolve(self) -> UUID:
        if self._resolved_id is None:
            self._resolved_id = self._runtimes._resolve(self._runtime)
        return self._resolved_id

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
        runtime_id = self._resolve()

        def refresher() -> RunnerSpec:
            return self._runtimes._post_run(runtime_id, options)

        return Runner(
            refresher(),
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


class _AsyncRuntimes:
    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def handle(self, runtime: str | UUID) -> AsyncRuntimeHandle:
        return AsyncRuntimeHandle(self, runtime=runtime)

    async def _resolve(self, runtime: str | UUID) -> UUID:
        payload = await self._http.request(
            "GET",
            "/v1/runtimes",
            params={"runtime": str(runtime), "limit": 2},
        )
        records = payload.get("records", [])
        if not records:
            raise LookupError(f"No runtime {runtime!r}")
        if len(records) > 1:
            raise LookupError(
                f"Ambiguous runtime {runtime!r}: {len(records)} matches"
            )
        return _ResolvedRuntime.model_validate(records[0]).id

    async def _post_run(
        self, runtime_id: UUID, options: RunRequest
    ) -> RunnerSpec:
        payload = await self._http.request(
            "POST",
            f"/v1/runtimes/{runtime_id}/run",
            json=options.model_dump(exclude_none=True, mode="json"),
        )
        return RunnerSpec.model_validate(payload)


class AsyncRuntimeHandle:
    """Async runtime runner opener."""

    def __init__(
        self, runtimes: _AsyncRuntimes, *, runtime: str | UUID
    ) -> None:
        self._runtimes = runtimes
        self._runtime = runtime
        self._resolved_id: UUID | None = None

    async def _resolve(self) -> UUID:
        if self._resolved_id is None:
            self._resolved_id = await self._runtimes._resolve(self._runtime)
        return self._resolved_id

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
        runtime_id = await self._resolve()

        async def refresher() -> RunnerSpec:
            return await self._runtimes._post_run(runtime_id, options)

        return AsyncRunner(
            await refresher(),
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


__all__ = ["AsyncRuntimeHandle", "RuntimeHandle"]
