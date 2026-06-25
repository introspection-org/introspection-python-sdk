"""``client.runtimes`` — CP CRUD + ``.run()`` returning a :class:`Runner`.

``client.runtimes`` is the :class:`Runtimes` instance; calling
``client.runtimes(id_or_slug)`` returns a :class:`RuntimeHandle`
which exposes ``.run()`` and ``.activate()``. When called with a
string that is not a UUID, the handle resolves it by slug on the
caller's project on first use.
"""

from __future__ import annotations

import re
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
from introspection_sdk.schemas.recipes import Recipe
from introspection_sdk.schemas.runner import (
    RunCaller,
    RunnerIdentity,
    RunnerSpec,
    RunRequest,
)
from introspection_sdk.schemas.runtimes import (
    Runtime,
    RuntimeCreate,
    RuntimeUpdate,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value))


class Runtimes:
    """CP ``/v1/runtimes`` namespace.

    Also callable: ``client.runtimes("runtime-slug")`` returns a
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
        self, id_or_slug: str | UUID, *, project_id: str | None = None
    ) -> RuntimeHandle:
        # The project is scoped by the API key server-side; `project_id` is an
        # explicit per-call override only — there is no client-level default.
        return RuntimeHandle(
            self,
            id_or_slug=id_or_slug,
            project_id=project_id,
        )

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project_id: str | None = None,
        slug: str | None = None,
        recipe_id: str | None = None,
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
                "project_id": project_id,
                "name": slug,
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

    def get(self, runtime_id: str | UUID, *, project_id: str) -> Runtime:
        payload = self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project_id": project_id},
        )
        return Runtime.model_validate(payload)

    def resolve_by_slug(
        self, slug: str, *, project_id: str | None = None
    ) -> Runtime:
        """Resolve an active runtime by slug on the caller's project.

        The standalone form of ``client.runtimes(slug)`` resolution —
        handy for a server broker that resolves a ``runtime_id`` to hand
        to a browser client (which talks only to the Data Plane and never
        resolves runtimes itself). The project is scoped by the token
        server-side; pass ``project_id`` only to override it.

        Raises ``LookupError`` if no active runtime matches the slug, or
        if the slug is ambiguous (more than one active match).
        """
        page = self.list(
            slug=slug,
            only_active=True,
            limit=2,
            project_id=project_id,
        ).page()
        if not page.records:
            raise LookupError(f"No active runtime with slug {slug!r}")
        if len(page.records) > 1:
            raise LookupError(
                f"Ambiguous runtime slug {slug!r}: "
                f"{len(page.records)} active matches"
            )
        return page.records[0]

    def create(self, input: RuntimeCreate | dict[str, Any]) -> Runtime:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RuntimeCreate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = self._http.request("POST", "/v1/runtimes", json=body)
        return Runtime.model_validate(payload)

    def update(
        self,
        runtime_id: str | UUID,
        input: RuntimeUpdate | dict[str, Any],
    ) -> Runtime:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RuntimeUpdate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json=body
        )
        return Runtime.model_validate(payload)

    def yank(
        self, runtime_id: str | UUID, *, reason: str | None = None
    ) -> Runtime:
        """Withdraw a runtime so it stops resolving as the active runtime for
        its environment. In-flight sticky runs keep using it; new runs fall
        back to the previous active runtime (or "none active" until a
        replacement is promoted)."""
        body: dict[str, Any] = {"yanked": True}
        if reason is not None:
            body["yanked_reason"] = reason
        payload = self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json=body
        )
        return Runtime.model_validate(payload)

    def unyank(self, runtime_id: str | UUID) -> Runtime:
        """Reverse a :meth:`yank`, making the runtime eligible to resolve
        again."""
        payload = self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json={"yanked": False}
        )
        return Runtime.model_validate(payload)

    # --- /run --------------------------------------------------------

    def _post_run(
        self,
        runtime_id: str | UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    def _activate(
        self,
        runtime_id: str | UUID,
        *,
        project_id: str | None,
    ) -> Runtime:
        body: dict[str, Any] = {}
        if project_id:
            body["project_id"] = project_id
        payload = self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/activate", json=body
        )
        return Runtime.model_validate(payload)


class RuntimeHandle:
    """Handle for a specific runtime (by id or by slug).

    Resolves a slug to an id lazily on first use by listing on the
    caller's project. Built by ``client.runtimes(id_or_slug)``.
    """

    def __init__(
        self,
        runtimes: Runtimes,
        *,
        id_or_slug: str | UUID,
        project_id: str | None,
        recipe_id: UUID | None = None,
    ) -> None:
        self._runtimes = runtimes
        self._project_id = project_id
        self._raw = id_or_slug
        self._resolved_id: str | None = None
        self._recipe_id: UUID | None = recipe_id

        if isinstance(id_or_slug, UUID):
            self._resolved_id = str(id_or_slug)
        elif isinstance(id_or_slug, str) and _looks_like_uuid(id_or_slug):
            self._resolved_id = id_or_slug

    @property
    def runtime_id(self) -> str:
        return self._resolve()

    def _resolve(self) -> str:
        if self._resolved_id is not None:
            return self._resolved_id
        runtime = self._runtimes.resolve_by_slug(
            str(self._raw), project_id=self._project_id
        )
        self._resolved_id = str(runtime.id)
        return self._resolved_id

    def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        ttl_seconds: int | None = 3600,
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
            ttl_seconds=ttl_seconds,
            recipe_id=self._recipe_id,
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

    def pin(self, recipe: Recipe | UUID | str) -> RuntimeHandle:
        """Pin this handle to a specific recipe.

        Returns a shallow-cloned :class:`RuntimeHandle` that captures
        the recipe id; subsequent ``.run()`` injects ``recipe_id`` into
        the ``RunRequest`` body. CP resolves the matching runtime row
        server-side (the row in this runtime's slug whose ``recipe_id``
        matches the pin).

        Accepts a :class:`Recipe` (uses its ``.id``), a ``UUID``, or a
        ``str`` parsed as a UUID.
        """
        if isinstance(recipe, Recipe):
            recipe_uuid = recipe.id
        elif isinstance(recipe, UUID):
            recipe_uuid = recipe
        else:
            recipe_uuid = UUID(recipe)
        clone = RuntimeHandle(
            self._runtimes,
            id_or_slug=self._raw,
            project_id=self._project_id,
            recipe_id=recipe_uuid,
        )
        # Preserve any resolution we've already done so the child
        # handle doesn't have to re-list by slug on first ``.run()``.
        clone._resolved_id = self._resolved_id
        return clone

    def activate(self, *, project_id: str | None = None) -> Runtime:
        rid = self._resolve()
        return self._runtimes._activate(
            rid, project_id=project_id or self._project_id
        )


class AsyncRuntimes:
    """Async twin of :class:`Runtimes` (CP ``/v1/runtimes``).

    Also callable: ``client.runtimes("runtime-slug")`` returns an
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
        self, id_or_slug: str | UUID, *, project_id: str | None = None
    ) -> AsyncRuntimeHandle:
        # The project is scoped by the API key server-side; `project_id` is an
        # explicit per-call override only — there is no client-level default.
        return AsyncRuntimeHandle(
            self,
            id_or_slug=id_or_slug,
            project_id=project_id,
        )

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project_id: str | None = None,
        slug: str | None = None,
        recipe_id: str | None = None,
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
                "project_id": project_id,
                "name": slug,
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

    async def get(self, runtime_id: str | UUID, *, project_id: str) -> Runtime:
        payload = await self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project_id": project_id},
        )
        return Runtime.model_validate(payload)

    async def resolve_by_slug(
        self, slug: str, *, project_id: str | None = None
    ) -> Runtime:
        """Async twin of :meth:`Runtimes.resolve_by_slug`.

        Resolve an active runtime by slug on the caller's project — the
        standalone form of ``client.runtimes(slug)`` resolution, handy
        for a server broker that resolves a ``runtime_id`` to hand to a
        browser client. Raises ``LookupError`` if no active runtime
        matches, or if the slug is ambiguous.
        """
        page = await self.list(
            slug=slug,
            only_active=True,
            limit=2,
            project_id=project_id,
        ).page()
        if not page.records:
            raise LookupError(f"No active runtime with slug {slug!r}")
        if len(page.records) > 1:
            raise LookupError(
                f"Ambiguous runtime slug {slug!r}: "
                f"{len(page.records)} active matches"
            )
        return page.records[0]

    async def create(self, input: RuntimeCreate | dict[str, Any]) -> Runtime:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RuntimeCreate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = await self._http.request("POST", "/v1/runtimes", json=body)
        return Runtime.model_validate(payload)

    async def update(
        self,
        runtime_id: str | UUID,
        input: RuntimeUpdate | dict[str, Any],
    ) -> Runtime:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, RuntimeUpdate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = await self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json=body
        )
        return Runtime.model_validate(payload)

    async def yank(
        self, runtime_id: str | UUID, *, reason: str | None = None
    ) -> Runtime:
        """Async twin of :meth:`Runtimes.yank`. Withdraw a runtime so it stops
        resolving as the active runtime for its environment; in-flight sticky
        runs keep using it."""
        body: dict[str, Any] = {"yanked": True}
        if reason is not None:
            body["yanked_reason"] = reason
        payload = await self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json=body
        )
        return Runtime.model_validate(payload)

    async def unyank(self, runtime_id: str | UUID) -> Runtime:
        """Reverse a :meth:`yank`, making the runtime eligible to resolve
        again."""
        payload = await self._http.request(
            "PATCH", f"/v1/runtimes/{runtime_id}", json={"yanked": False}
        )
        return Runtime.model_validate(payload)

    # --- /run --------------------------------------------------------

    async def _post_run(
        self,
        runtime_id: str | UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = await self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    async def _activate(
        self,
        runtime_id: str | UUID,
        *,
        project_id: str | None,
    ) -> Runtime:
        body: dict[str, Any] = {}
        if project_id:
            body["project_id"] = project_id
        payload = await self._http.request(
            "POST", f"/v1/runtimes/{runtime_id}/activate", json=body
        )
        return Runtime.model_validate(payload)


class AsyncRuntimeHandle:
    """Async twin of :class:`RuntimeHandle`.

    Resolves a slug to an id lazily on first use by listing on the
    caller's project. Built by ``client.runtimes(id_or_slug)``.
    """

    def __init__(
        self,
        runtimes: AsyncRuntimes,
        *,
        id_or_slug: str | UUID,
        project_id: str | None,
        recipe_id: UUID | None = None,
    ) -> None:
        self._runtimes = runtimes
        self._project_id = project_id
        self._raw = id_or_slug
        self._resolved_id: str | None = None
        self._recipe_id: UUID | None = recipe_id

        if isinstance(id_or_slug, UUID):
            self._resolved_id = str(id_or_slug)
        elif isinstance(id_or_slug, str) and _looks_like_uuid(id_or_slug):
            self._resolved_id = id_or_slug

    async def _resolve(self) -> str:
        if self._resolved_id is not None:
            return self._resolved_id
        runtime = await self._runtimes.resolve_by_slug(
            str(self._raw), project_id=self._project_id
        )
        self._resolved_id = str(runtime.id)
        return self._resolved_id

    async def run(
        self,
        *,
        identity: RunnerIdentity | dict[str, Any] | None = None,
        caller: RunCaller | dict[str, Any] | None = None,
        ttl_seconds: int | None = 3600,
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
            ttl_seconds=ttl_seconds,
            recipe_id=self._recipe_id,
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

    def pin(self, recipe: Recipe | UUID | str) -> AsyncRuntimeHandle:
        """Pin this handle to a specific recipe.

        Returns a shallow-cloned :class:`AsyncRuntimeHandle` that captures
        the recipe id; subsequent ``.run()`` injects ``recipe_id`` into
        the ``RunRequest`` body. Accepts a :class:`Recipe` (uses its
        ``.id``), a ``UUID``, or a ``str`` parsed as a UUID.
        """
        if isinstance(recipe, Recipe):
            recipe_uuid = recipe.id
        elif isinstance(recipe, UUID):
            recipe_uuid = recipe
        else:
            recipe_uuid = UUID(recipe)
        clone = AsyncRuntimeHandle(
            self._runtimes,
            id_or_slug=self._raw,
            project_id=self._project_id,
            recipe_id=recipe_uuid,
        )
        # Preserve any resolution we've already done so the child
        # handle doesn't have to re-list by slug on first ``.run()``.
        clone._resolved_id = self._resolved_id
        return clone

    async def activate(self, *, project_id: str | None = None) -> Runtime:
        rid = await self._resolve()
        return await self._runtimes._activate(
            rid, project_id=project_id or self._project_id
        )


__all__ = [
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "RuntimeHandle",
    "Runtimes",
]
