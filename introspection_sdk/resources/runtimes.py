"""``client.runtimes`` — CP CRUD + ``.run()`` returning a :class:`Runner`.

``client.runtimes`` is the :class:`Runtimes` instance; calling
``client.runtimes(id_or_name)`` returns a :class:`RuntimeHandle`
which exposes ``.run()`` and ``.activate()``. When called with a
string that is not a UUID, the handle resolves it by name on the
caller's project on first use.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _HttpClient
from introspection_sdk.runner import Runner
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

    Also callable: ``client.runtimes("name")`` returns a
    :class:`RuntimeHandle` for that runtime.
    """

    def __init__(
        self,
        http: _HttpClient,
        *,
        default_project_id: str | None = None,
        additional_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        self._default_project_id = default_project_id
        self._additional_headers = additional_headers

    def __call__(
        self, id_or_name: str | UUID, *, project_id: str | None = None
    ) -> RuntimeHandle:
        return RuntimeHandle(
            self,
            id_or_name=id_or_name,
            project_id=project_id or self._default_project_id,
        )

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project_id: str | None = None,
        name: str | None = None,
        recipe_id: str | None = None,
        only_active: bool | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> Paginated[Runtime]:
        params: dict[str, Any] = {
            "project_id": project_id,
            "name": name,
            "recipe_id": recipe_id,
            "only_active": only_active,
            "limit": limit,
            "next": next,
        }
        payload = self._http.request("GET", "/v1/runtimes", params=params)
        return Paginated[Runtime].model_validate(payload)

    def iter(self, **filters: Any) -> Iterator[Runtime]:
        next_token: str | None = filters.pop("next", None)
        while True:
            page = self.list(next=next_token, **filters)
            yield from page.records
            if not page.next:
                return
            next_token = page.next

    def get(self, runtime_id: str | UUID, *, project_id: str) -> Runtime:
        payload = self._http.request(
            "GET",
            f"/v1/runtimes/{runtime_id}",
            params={"project_id": project_id},
        )
        return Runtime.model_validate(payload)

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
    """Handle for a specific runtime (by id or by name).

    Resolves a name to an id lazily on first use by listing on the
    caller's project. Built by ``client.runtimes(id_or_name)``.
    """

    def __init__(
        self,
        runtimes: Runtimes,
        *,
        id_or_name: str | UUID,
        project_id: str | None,
        recipe_id: UUID | None = None,
    ) -> None:
        self._runtimes = runtimes
        self._project_id = project_id
        self._raw = id_or_name
        self._resolved_id: str | None = None
        self._recipe_id: UUID | None = recipe_id

        if isinstance(id_or_name, UUID):
            self._resolved_id = str(id_or_name)
        elif isinstance(id_or_name, str) and _looks_like_uuid(id_or_name):
            self._resolved_id = id_or_name

    @property
    def runtime_id(self) -> str:
        return self._resolve()

    def _resolve(self) -> str:
        if self._resolved_id is not None:
            return self._resolved_id
        name = str(self._raw)
        params: dict[str, Any] = {
            "name": name,
            "only_active": True,
            "limit": 2,
        }
        if self._project_id:
            params["project_id"] = self._project_id
        page = self._runtimes.list(**params)
        if not page.records:
            raise LookupError(f"No active runtime named {name!r}")
        if len(page.records) > 1:
            raise LookupError(
                f"Ambiguous runtime name {name!r}: "
                f"{len(page.records)} active matches"
            )
        self._resolved_id = str(page.records[0].id)
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
        server-side (the row in this runtime's name whose ``recipe_id``
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
            id_or_name=self._raw,
            project_id=self._project_id,
            recipe_id=recipe_uuid,
        )
        # Preserve any resolution we've already done so the child
        # handle doesn't have to re-list by name on first ``.run()``.
        clone._resolved_id = self._resolved_id
        return clone

    def activate(self, *, project_id: str | None = None) -> Runtime:
        rid = self._resolve()
        return self._runtimes._activate(
            rid, project_id=project_id or self._project_id
        )


__all__ = ["RuntimeHandle", "Runtimes"]
