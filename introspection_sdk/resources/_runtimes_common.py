"""Code shared by the sync and async twins in :mod:`introspection_sdk.resources.runtimes`.

:class:`RuntimeHandle` and :class:`AsyncRuntimeHandle` are written by hand
rather than generated: ``runtime_id`` is a property on one and a coroutine
on the other, which unasync cannot express.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._errors import NotFoundError
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)

if TYPE_CHECKING:
    from introspection_sdk.resources.runtimes import AsyncRuntimes, Runtimes


class RuntimeHandle:
    """Handle for a specific runtime slug or runtime group id.

    Holds the stable selector and resolves it on each use. ``run()`` posts a
    slug straight to ``/v1/runtimes/{slug}/run``, which resolves it in the
    caller's project, so a credential refused the list (a ``customer``
    signed in by email code) can still open a runner. A runtime group id has
    no such route and is resolved by listing on the caller's project. Built
    by ``client.runtimes(runtime)``.

    The resolved row id is deliberately not cached. A runtime group's versions
    change underneath a long-lived handle: deploys add them, and yanking or
    deleting retires them. A handle that remembered its first answer went on
    using a version that could since have been withdrawn, so every later
    ``run()`` failed with a 404 no caller could clear short of rebuilding the
    handle. Holding the selector instead costs one lookup per use and always
    reaches whatever the group currently serves.
    """

    def __init__(
        self,
        runtimes: Runtimes,
        *,
        runtime: str | UUID,
        project: str | None,
        resolved: bool = False,
    ) -> None:
        self._runtimes = runtimes
        self._project = project
        self._raw = runtime
        self._resolved = resolved

    @property
    def runtime_id(self) -> UUID:
        return self._resolve()

    def _resolve(self) -> UUID:
        if self._resolved:
            return UUID(str(self._raw))
        return self._runtimes.resolve(str(self._raw), project=self._project).id

    def _run_target(self) -> UUID | str:
        if self._resolved or _is_uuid(self._raw):
            return self._resolve()
        return str(self._raw)

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
        target = self._run_target()

        def refresher() -> RunnerSpec:
            return self._runtimes._post_run(
                target, options, project=self._project
            )

        spec = refresher()
        return Runner(
            spec,
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


class AsyncRuntimeHandle:
    """Async twin of :class:`RuntimeHandle`.

    Holds the stable selector and resolves it on each use: ``run()`` posts a
    slug straight to ``/v1/runtimes/{slug}/run`` and lists only to resolve a
    runtime group id. Built by ``client.runtimes(runtime)``. See
    :class:`RuntimeHandle` for why the resolved id is not cached.
    """

    def __init__(
        self,
        runtimes: AsyncRuntimes,
        *,
        runtime: str | UUID,
        project: str | None,
        resolved: bool = False,
    ) -> None:
        self._runtimes = runtimes
        self._project = project
        self._raw = runtime
        self._resolved = resolved

    async def runtime_id(self) -> UUID:
        """Resolve the concrete runtime id this handle currently serves.

        The async twin of :attr:`RuntimeHandle.runtime_id`. A coroutine
        rather than a property because resolving costs a request, and a
        property cannot be awaited. Without it the async client had no
        public way to read the id a handle resolves to — the broker case
        the sync property exists for.
        """
        return await self._resolve()

    async def _resolve(self) -> UUID:
        if self._resolved:
            return UUID(str(self._raw))
        resolved = await self._runtimes.resolve(
            str(self._raw), project=self._project
        )
        return resolved.id

    async def _run_target(self) -> UUID | str:
        if self._resolved or _is_uuid(self._raw):
            return await self._resolve()
        return str(self._raw)

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
        target = await self._run_target()

        async def refresher() -> RunnerSpec:
            return await self._runtimes._post_run(
                target, options, project=self._project
            )

        spec = await refresher()
        return AsyncRunner(
            spec,
            refresher=refresher,
            additional_headers=self._runtimes._additional_headers,
        )


def _no_runtime(runtime: str | UUID) -> NotFoundError:
    """The error a resolve-by-selector miss raises.

    A miss here is an empty list page rather than a ``404`` from the route,
    so the status has to be supplied. It is still a 404: the caller named a
    runtime the project does not serve, which is the same answer
    ``GET /v1/runtimes/{id}`` gives, and a caller handling "not there"
    should not have to catch a second, unrelated exception type to cover
    the selector form.
    """
    return NotFoundError(
        f"No runtime {str(runtime)!r}",
        status_code=404,
        code="not_found",
    )


def _is_uuid(selector: str | UUID) -> bool:
    if isinstance(selector, UUID):
        return True
    try:
        UUID(selector)
    except ValueError:
        return False
    return True


def _run_path(runtime: UUID | str) -> str:
    return f"/v1/runtimes/{quote(str(runtime), safe='')}/run"
