"""Re-exported by :mod:`introspection_sdk.resources.runtimes`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._errors import NotFoundError
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.resources._runtimes_common import (
    AsyncRuntimeHandle,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.runner import (
    RunnerSpec,
    RunRequest,
)
from introspection_sdk.schemas.runtimes import Runtime


class AsyncRuntimes:
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`Runtimes` (CP ``/v1/runtimes``).

    Also callable: ``client.runtimes("runtime")`` returns an
    :class:`AsyncRuntimeHandle` for that runtime.
    """

    # unasync: end
    """CP ``/v1/runtimes`` namespace.

    Also callable: ``client.runtimes("runtime")`` returns a
    :class:`RuntimeHandle` for that runtime.
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

    def handle(self, runtime_id: UUID) -> AsyncRuntimeHandle:
        """Bind a handle to a concrete ``runtime_id``, skipping resolution.

        ``client.runtimes(selector)`` holds a slug or runtime group id and
        resolves it on every use to find what the group currently serves. Pass a
        runtime id there and the lookup answers nothing: the ``runtime``
        filter matches slugs and group ids, not the row's own id. Use this
        when the id is already known — from ``resolve()``, ``get()``, or a
        broker that handed it over.
        """
        return AsyncRuntimeHandle(
            self,
            runtime=runtime_id,
            project=None,
            resolved=True,
        )

    # Runtime lifecycle and version selection are managed by the CLI and
    # platform. The SDK intentionally exposes only read, resolve, and run.

    def list(
        self,
        *,
        project: str | None = None,
        runtime: str | None = None,
        recipe_id: UUID | None = None,
        environment: str | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> AsyncPager[Runtime, Paginated[Runtime]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List runtimes. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every runtime across
        pages.

        Pass ``environment`` to restrict to runtimes serving that lane. An
        API key already selects its environment, so passing both is a 400."""
        # unasync: end
        """List runtimes. Iterate the returned :class:`Pager` to stream
        every runtime across pages, or call ``.page()`` for the first page
        only.

        Pass ``environment`` to restrict to runtimes serving that lane. An
        API key already selects its environment, so passing both is a 400."""

        async def fetch(cursor: str | None) -> Paginated[Runtime]:
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
            return Paginated[Runtime].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(
        self, runtime_id: UUID, *, project: str | None = None
    ) -> Runtime:
        payload = await self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project": project},
        )
        return Runtime.model_validate(payload)

    async def resolve(
        self, runtime: str | UUID, *, project: str | None = None
    ) -> Runtime:
        # unasync: async-only (the sync twin's docstring follows)
        """Async twin of :meth:`Runtimes.resolve`.

        Resolve a runtime by slug or runtime group id on the caller's project — the
        standalone form of ``client.runtimes(runtime)`` resolution, handy
        for a server broker that resolves a concrete ``runtime_id`` to hand to a
        browser client. Resolves to the newest runtime for the selector;
        raises :class:`~introspection_sdk.NotFoundError` if nothing matches.
        """
        # unasync: end
        """Resolve a runtime by slug or runtime group id.

        The standalone form of ``client.runtimes(runtime)`` resolution —
        handy for a server broker that resolves a concrete ``runtime_id`` to hand
        to a browser client (which talks only to the Data Plane and never
        resolves runtimes itself). The project is scoped by the token
        server-side; pass ``project`` only to override it.

        The route answers newest-first and has no notion of a single
        "active" row for a development credential, so a slug that has
        been published more than once resolves to its newest runtime
        rather than failing as ambiguous.

        Raises :class:`~introspection_sdk.NotFoundError` if nothing matches
        the slug or runtime group id — the same error
        :meth:`get` raises for a runtime that is not there, so one
        ``except`` covers both ways of asking for one.
        """
        page = await self.list(
            runtime=str(runtime),
            limit=1,
            project=project,
        ).page()
        if not page.records:
            raise _no_runtime(runtime)
        return page.records[0]

    # --- /run --------------------------------------------------------

    async def _post_run(
        self,
        runtime: UUID | str,
        options: RunRequest,
        *,
        project: str | None = None,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = await self._http.request(
            "POST",
            _run_path(runtime),
            params={"project": project},
            json=body,
        )
        return RunnerSpec.model_validate(payload)


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


def _run_path(runtime: UUID | str) -> str:
    return f"/v1/runtimes/{quote(str(runtime), safe='')}/run"
