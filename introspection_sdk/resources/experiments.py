"""``client.experiments`` — CP CRUD + lifecycle + ``.run()`` returning a
:class:`Runner`.

``client.experiments`` is the :class:`Experiments` instance; calling
``client.experiments(id)`` returns an :class:`ExperimentHandle` with
``.run()``, ``.start()``, ``.end(...)``, and ``.cancel()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from introspection_sdk._http import _HttpClient
from introspection_sdk.pagination import Pager, cursor_paginate
from introspection_sdk.runner import Runner
from introspection_sdk.schemas.experiments import (
    Experiment,
    ExperimentCreate,
    ExperimentUpdate,
)
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

    def __call__(self, experiment_id: str | UUID) -> ExperimentHandle:
        return ExperimentHandle(self, experiment_id=experiment_id)

    # --- CRUD --------------------------------------------------------

    def list(
        self,
        *,
        project_id: str,
        name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        next: str | None = None,
    ) -> Pager[Experiment, Paginated[Experiment]]:
        """List experiments. Iterate the returned :class:`Pager` to stream
        every experiment across pages, or call ``.page()`` for the first
        page only."""

        def fetch(cursor: str | None) -> Paginated[Experiment]:
            params: dict[str, Any] = {
                "project_id": project_id,
                "name": name,
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
        self, experiment_id: str | UUID, *, project_id: str | None = None
    ) -> Experiment:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        payload = self._http.request(
            "GET",
            f"/v1/experiments/{experiment_id}",
            params=params or None,
        )
        return Experiment.model_validate(payload)

    def create(self, input: ExperimentCreate | dict[str, Any]) -> Experiment:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, ExperimentCreate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = self._http.request("POST", "/v1/experiments", json=body)
        return Experiment.model_validate(payload)

    def update(
        self,
        experiment_id: str | UUID,
        input: ExperimentUpdate | dict[str, Any],
    ) -> Experiment:
        body = (
            input.model_dump(exclude_none=True, mode="json")
            if isinstance(input, ExperimentUpdate)
            else {k: v for k, v in input.items() if v is not None}
        )
        payload = self._http.request(
            "PATCH", f"/v1/experiments/{experiment_id}", json=body
        )
        return Experiment.model_validate(payload)

    def delete(self, experiment_id: str | UUID) -> None:
        self._http.request(
            "DELETE",
            f"/v1/experiments/{experiment_id}",
            expect="empty",
        )

    # --- /run + lifecycle -------------------------------------------

    def _post_run(
        self,
        experiment_id: str | UUID,
        options: RunRequest,
    ) -> RunnerSpec:
        body: dict[str, Any] = options.model_dump(
            exclude_none=True, mode="json"
        )
        payload = self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/run", json=body
        )
        return RunnerSpec.model_validate(payload)

    def _start(self, experiment_id: str | UUID) -> Experiment:
        payload = self._http.request(
            "POST", f"/v1/experiments/{experiment_id}/start"
        )
        return Experiment.model_validate(payload)

    def _end(
        self,
        experiment_id: str | UUID,
        *,
        winning_arm_label: str | None = None,
        notes: str | None = None,
    ) -> Experiment:
        body: dict[str, Any] = {}
        if winning_arm_label is not None:
            body["winning_arm_label"] = winning_arm_label
        if notes is not None:
            body["notes"] = notes
        payload = self._http.request(
            "POST",
            f"/v1/experiments/{experiment_id}/end",
            json=body,
        )
        return Experiment.model_validate(payload)

    def _cancel(self, experiment_id: str | UUID) -> Experiment:
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
        experiment_id: str | UUID,
    ) -> None:
        self._experiments = experiments
        self._experiment_id = (
            str(experiment_id)
            if isinstance(experiment_id, UUID)
            else experiment_id
        )

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

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
            identity=ident, caller=call, ttl_seconds=ttl_seconds
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

    def end(
        self,
        *,
        winning_arm_label: str | None = None,
        notes: str | None = None,
    ) -> Experiment:
        return self._experiments._end(
            self._experiment_id,
            winning_arm_label=winning_arm_label,
            notes=notes,
        )

    def cancel(self) -> Experiment:
        return self._experiments._cancel(self._experiment_id)


__all__ = ["ExperimentHandle", "Experiments"]
