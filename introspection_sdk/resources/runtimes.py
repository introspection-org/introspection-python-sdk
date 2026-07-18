"""``client.runtimes`` — read, resolve, and run runtimes.

``client.runtimes`` is the :class:`Runtimes` instance; calling
``client.runtimes(runtime)`` returns a :class:`RuntimeHandle`
which exposes ``.run()``. When called with a
runtime slug or UUID, the handle resolves it on the caller's project
on first use. UUID selectors are runtime group IDs; concrete runtime
row IDs are used only by explicit ``*_id`` methods.
"""

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
from introspection_sdk.schemas.runtimes import Runtime


class Runtimes:
    """CP ``/v1/runtimes`` namespace.

    Also callable: ``client.runtimes("runtime")`` returns a
    :class:`RuntimeHandle` for that runtime.
    """

    def __init__(
        self,
        http: _HttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def __call__(
        self, runtime: str | UUID, *, project: str | None = None
    ) -> RuntimeHandle:
        # The project is scoped by the API key server-side; `project` is an
        # explicit per-call override only — there is no client-level default.
        return RuntimeHandle(
            self,
            runtime=runtime,
            project=project,
        )

    # Runtime lifecycle and version selection are managed by the CLI and
    # platform. The SDK intentionally exposes only read, resolve, and run.

    def list(
        self,
        *,
        project: str | None = None,
        runtime: str | None = None,
        recipe_id: UUID | None = None,
        only_active: bool | None = None,
        environment: str | None = None,
        exclude_yanked: bool | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> Pager[Runtime, Paginated[Runtime]]:
        """List runtimes. Iterate the returned :class:`Pager` to stream
        every runtime across pages, or call ``.page()`` for the first page
        only.

        Pass ``environment`` to restrict to runtimes serving that lane and
        ``exclude_yanked=True`` to omit withdrawn runtimes (mirrors the
        server-side active resolution)."""

        def fetch(cursor: str | None) -> Paginated[Runtime]:
            params: dict[str, Any] = {
                "project": project,
                "runtime": runtime,
                "recipe_id": recipe_id,
                "only_active": only_active,
                "environment": environment,
                "exclude_yanked": exclude_yanked,
                "limit": limit,
                "next": cursor,
            }
            payload = self._http.request("GET", "/v1/runtimes", params=params)
            return Paginated[Runtime].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(self, runtime_id: UUID, *, project: str) -> Runtime:
        payload = self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project": project},
        )
        return Runtime.model_validate(payload)

    def resolve(
        self, runtime: str | UUID, *, project: str | None = None
    ) -> Runtime:
        """Resolve an active runtime by slug or runtime group id.

        The standalone form of ``client.runtimes(runtime)`` resolution —
        handy for a server broker that resolves a concrete ``runtime_id`` to hand
        to a browser client (which talks only to the Data Plane and never
        resolves runtimes itself). The project is scoped by the token
        server-side; pass ``project`` only to override it.

        Raises ``LookupError`` if no active runtime matches the slug or
        runtime group id, or if the selector is ambiguous (more than one active
        match).
        """
        page = self.list(
            runtime=str(runtime),
            only_active=True,
            limit=2,
            project=project,
        ).page()
        if not page.records:
            raise LookupError(f"No active runtime {runtime!r}")
        if len(page.records) > 1:
            raise LookupError(
                f"Ambiguous runtime {runtime!r}: "
                f"{len(page.records)} active matches"
            )
        return page.records[0]

    # --- /run --------------------------------------------------------

    def _post_run(
        self,
        runtime_id: UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)


class RuntimeHandle:
    """Handle for a specific runtime slug or runtime group id.

    Resolves the selector lazily on first use by listing on the caller's
    project. Built by ``client.runtimes(runtime)``.
    """

    def __init__(
        self,
        runtimes: Runtimes,
        *,
        runtime: str | UUID,
        project: str | None,
    ) -> None:
        self._runtimes = runtimes
        self._project = project
        self._raw = runtime
        self._resolved_id: UUID | None = None

    @property
    def runtime_id(self) -> UUID:
        return self._resolve()

    def _resolve(self) -> UUID:
        if self._resolved_id is not None:
            return self._resolved_id
        runtime = self._runtimes.resolve(str(self._raw), project=self._project)
        self._resolved_id = runtime.id
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
        rid = self._resolve()

        def refresher() -> RunnerSpec:
            return self._runtimes._post_run(rid, options)

        spec = refresher()
        return Runner(
            spec,
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


class AsyncRuntimes:
    """Async twin of :class:`Runtimes` (CP ``/v1/runtimes``).

    Also callable: ``client.runtimes("runtime")`` returns an
    :class:`AsyncRuntimeHandle` for that runtime.
    """

    def __init__(
        self,
        http: _AsyncHttpClient,
        *,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._additional_headers = additional_headers

    def __call__(
        self, runtime: str | UUID, *, project: str | None = None
    ) -> AsyncRuntimeHandle:
        # The project is scoped by the API key server-side; `project` is an
        # explicit per-call override only — there is no client-level default.
        return AsyncRuntimeHandle(
            self,
            runtime=runtime,
            project=project,
        )

    # Runtime lifecycle and version selection are managed by the CLI and
    # platform. The SDK intentionally exposes only read, resolve, and run.

    def list(
        self,
        *,
        project: str | None = None,
        runtime: str | None = None,
        recipe_id: UUID | None = None,
        only_active: bool | None = None,
        environment: str | None = None,
        exclude_yanked: bool | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> AsyncPager[Runtime, Paginated[Runtime]]:
        """List runtimes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every runtime across
        pages.

        Pass ``environment`` to restrict to runtimes serving that lane and
        ``exclude_yanked=True`` to omit withdrawn runtimes (mirrors the
        server-side active resolution)."""

        async def fetch(cursor: str | None) -> Paginated[Runtime]:
            params: dict[str, Any] = {
                "project": project,
                "runtime": runtime,
                "recipe_id": recipe_id,
                "only_active": only_active,
                "environment": environment,
                "exclude_yanked": exclude_yanked,
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/runtimes", params=params
            )
            return Paginated[Runtime].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, runtime_id: UUID, *, project: str) -> Runtime:
        payload = await self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project": project},
        )
        return Runtime.model_validate(payload)

    async def resolve(
        self, runtime: str | UUID, *, project: str | None = None
    ) -> Runtime:
        """Async twin of :meth:`Runtimes.resolve`.

        Resolve an active runtime by slug or runtime group id on the caller's project — the
        standalone form of ``client.runtimes(runtime)`` resolution, handy
        for a server broker that resolves a concrete ``runtime_id`` to hand to a
        browser client. Raises ``LookupError`` if no active runtime
        matches, or if the selector is ambiguous.
        """
        page = await self.list(
            runtime=str(runtime),
            only_active=True,
            limit=2,
            project=project,
        ).page()
        if not page.records:
            raise LookupError(f"No active runtime {runtime!r}")
        if len(page.records) > 1:
            raise LookupError(
                f"Ambiguous runtime {runtime!r}: "
                f"{len(page.records)} active matches"
            )
        return page.records[0]

    # --- /run --------------------------------------------------------

    async def _post_run(
        self,
        runtime_id: UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = await self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)


class AsyncRuntimeHandle:
    """Async twin of :class:`RuntimeHandle`.

    Resolves the selector lazily on first use by listing on the caller's
    project. Built by ``client.runtimes(runtime)``.
    """

    def __init__(
        self,
        runtimes: AsyncRuntimes,
        *,
        runtime: str | UUID,
        project: str | None,
    ) -> None:
        self._runtimes = runtimes
        self._project = project
        self._raw = runtime
        self._resolved_id: UUID | None = None

    async def _resolve(self) -> UUID:
        if self._resolved_id is not None:
            return self._resolved_id
        runtime = await self._runtimes.resolve(
            str(self._raw), project=self._project
        )
        self._resolved_id = runtime.id
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
        rid = await self._resolve()

        async def refresher() -> RunnerSpec:
            return await self._runtimes._post_run(rid, options)

        spec = await refresher()
        return AsyncRunner(
            spec,
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


__all__ = [
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "RuntimeHandle",
    "Runtimes",
]
