"""``client.runtimes`` — read Runtime versions and create Runners."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)
from introspection_sdk.schemas.runtimes import (
    RuntimeEnvironment,
    RuntimeVersion,
)


class Runtimes:
    """CP ``/v1/runtimes`` namespace."""

    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    # Runtime lifecycle and version selection are managed by the CLI and
    # platform. The SDK exposes reads plus stable and exact Runner creation.

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime: str | None = None,
        recipe_id: UUID | None = None,
        environment: RuntimeEnvironment | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> Pager[RuntimeVersion, Paginated[RuntimeVersion]]:
        """List runtimes. Iterate the returned :class:`Pager` to stream
        every runtime across pages, or call ``.page()`` for the first page
        only.

        Pass ``environment`` to restrict to runtimes serving that lane and
        the selected lane."""

        def fetch(cursor: str | None) -> Paginated[RuntimeVersion]:
            params: dict[str, Any] = {
                "project": project,
                "runtime": runtime,
                "recipe_id": recipe_id,
                "environment": environment,
                "limit": limit,
                "next": cursor,
            }
            payload = self._http.request("GET", "/v1/runtimes", params=params)
            return Paginated[RuntimeVersion].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(
        self, runtime_id: UUID, *, project: str | UUID | None = None
    ) -> RuntimeVersion:
        payload = self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project": project},
        )
        return RuntimeVersion.model_validate(payload)

    # --- /run --------------------------------------------------------

    def _post_run(
        self,
        *,
        runtime: str | UUID | None = None,
        runtime_id: UUID | None = None,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        if runtime is not None:
            body["runtime"] = str(runtime)
        if runtime_id is not None:
            body["runtime_id"] = str(runtime_id)
        payload = self._http.request("POST", "/v1/runtimes/run", json=body)
        return RunnerSpec.model_validate(payload)

    def run(
        self,
        *,
        runtime: str | UUID | None = None,
        runtime_id: UUID | None = None,
        project: str | UUID | None = None,
        environment: RuntimeEnvironment | None = None,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = None,
        scope: str | None = None,
        bindings_required: bool | None = None,
    ) -> Runner:
        """Run either a stable Runtime or one exact Runtime version."""
        _validate_selector(runtime=runtime, runtime_id=runtime_id)
        options = _run_request(
            project=project,
            environment=environment,
            identity=identity,
            caller=caller,
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
            bindings_required=bindings_required,
        )

        return Runner(
            self._post_run(
                runtime=runtime,
                runtime_id=runtime_id,
                options=options,
            ),
            additional_headers=self._additional_headers,
        )


class AsyncRuntimes:
    """Async twin of :class:`Runtimes` (CP ``/v1/runtimes``)."""

    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    # Runtime lifecycle and version selection are managed by the CLI and
    # platform. The SDK exposes reads plus stable and exact Runner creation.

    def list(
        self,
        *,
        project: str | UUID | None = None,
        runtime: str | None = None,
        recipe_id: UUID | None = None,
        environment: RuntimeEnvironment | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> AsyncPager[RuntimeVersion, Paginated[RuntimeVersion]]:
        """List runtimes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every runtime across
        pages.

        Pass ``environment`` to restrict to runtimes serving that lane and
        the selected lane."""

        async def fetch(
            cursor: str | None,
        ) -> Paginated[RuntimeVersion]:
            params: dict[str, Any] = {
                "project": project,
                "runtime": runtime,
                "recipe_id": recipe_id,
                "environment": environment,
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/runtimes", params=params
            )
            return Paginated[RuntimeVersion].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(
        self, runtime_id: UUID, *, project: str | UUID | None = None
    ) -> RuntimeVersion:
        payload = await self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project": project},
        )
        return RuntimeVersion.model_validate(payload)

    # --- /run --------------------------------------------------------

    async def _post_run(
        self,
        *,
        runtime: str | UUID | None = None,
        runtime_id: UUID | None = None,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        if runtime is not None:
            body["runtime"] = str(runtime)
        if runtime_id is not None:
            body["runtime_id"] = str(runtime_id)
        payload = await self._http.request(
            "POST", "/v1/runtimes/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    async def run(
        self,
        *,
        runtime: str | UUID | None = None,
        runtime_id: UUID | None = None,
        project: str | UUID | None = None,
        environment: RuntimeEnvironment | None = None,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        agent_name: str | None = None,
        ttl_seconds: int | None = None,
        scope: str | None = None,
        bindings_required: bool | None = None,
    ) -> AsyncRunner:
        """Run either a stable Runtime or one exact Runtime version."""
        _validate_selector(runtime=runtime, runtime_id=runtime_id)
        options = _run_request(
            project=project,
            environment=environment,
            identity=identity,
            caller=caller,
            agent_name=agent_name,
            ttl_seconds=ttl_seconds,
            scope=scope,
            bindings_required=bindings_required,
        )

        return AsyncRunner(
            await self._post_run(
                runtime=runtime,
                runtime_id=runtime_id,
                options=options,
            ),
            additional_headers=self._additional_headers,
        )


def _run_request(
    *,
    project: str | UUID | None,
    environment: RuntimeEnvironment | None,
    identity: RunnerIdentity | dict[str, Any] | None,
    caller: RunCaller | dict[str, Any] | None,
    agent_name: str | None,
    ttl_seconds: int | None,
    scope: str | None,
    bindings_required: bool | None,
) -> RunRequest:
    ident = (
        identity
        if identity is None or isinstance(identity, RunnerIdentity)
        else RunnerIdentity.model_validate(identity)
    )
    call = (
        caller
        if caller is None or isinstance(caller, RunCaller)
        else RunCaller.model_validate(caller)
    )
    return RunRequest(
        project=project,
        environment=environment,
        identity=ident,
        caller=call,
        agent_name=agent_name,
        ttl_seconds=ttl_seconds,
        scope=scope,
        bindings_required=bindings_required,
    )


def _validate_selector(
    *,
    runtime: str | UUID | None,
    runtime_id: UUID | None,
) -> None:
    if (runtime is None) == (runtime_id is None):
        raise ValueError("exactly one of runtime or runtime_id is required")


__all__ = [
    "AsyncRuntimes",
    "Runtimes",
]
