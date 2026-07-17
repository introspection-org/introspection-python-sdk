"""`runner.tasks.*` namespace: tasks + runs + cursor-style sugar.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.resumable import (
    stream_resumable,
    stream_resumable_async,
)
from introspection_sdk.schemas.agui import (
    AGUIEvent,
    ResumeEntry,
    TextMessageChunkEvent,
    TextMessageContentEvent,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelRequest,
    TaskCancelResponse,
    TaskCreateResponse,
    TaskMode,
    TaskPrompt,
    TaskRun,
    TaskRunKind,
    TaskRunResponse,
)


def _resume_body(
    resume: list[ResumeEntry | dict[str, Any]],
) -> dict[str, Any]:
    return {
        "resume": [
            entry.model_dump(exclude_none=True, by_alias=True)
            if isinstance(entry, ResumeEntry)
            else entry
            for entry in resume
        ]
    }


class RunHandle:
    """Returned by ``Tasks.start(...)`` and ``TaskRuns.create(...)``.

    Mirrors the Cursor SDK shape: ``handle.stream()`` to iterate validated
    AG-UI events, ``handle.text()`` to collect text deltas into a string,
    ``handle.cancel()`` for the default abort behavior, with typed options for
    explicit abort or drain cancellation.
    """

    def __init__(
        self,
        task: Task | None,
        run: TaskRun,
        runs: TaskRuns,
    ) -> None:
        self.task = task
        self.run = run
        self._runs = runs

    def stream(
        self,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> Iterator[AGUIEvent]:
        return self._runs.stream(
            str(self.run.task_id),
            self.run.id,
            max_reconnects=max_reconnects,
            backoff=backoff,
            timeout=timeout,
        )

    def cancel(
        self,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse:
        return self._runs.cancel(
            str(self.run.task_id), self.run.id, options=options
        )

    def text(self) -> str:
        out: list[str] = []
        for ev in self.stream():
            if isinstance(ev, TextMessageContentEvent | TextMessageChunkEvent):
                out.append(str(ev.delta or ""))
        return "".join(out)


class TaskRuns:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def create(
        self,
        task_id: str,
        *,
        prompt: TaskPrompt | dict[str, Any] | None = None,
        message: str | None = None,
        kind: TaskRunKind | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunHandle:
        body: dict[str, Any] = {}
        if prompt is not None:
            body["prompt"] = (
                prompt.model_dump(exclude_none=True)
                if isinstance(prompt, TaskPrompt)
                else prompt
            )
        if message is not None:
            body["message"] = message
        if kind is not None:
            body["kind"] = (
                kind.value if isinstance(kind, TaskRunKind) else kind
            )
        if metadata is not None:
            body["metadata"] = metadata
        payload = self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=body
        )
        res = TaskRunResponse.model_validate(payload)
        return RunHandle(None, res.run, self)

    def resume(
        self,
        task_id: str,
        *,
        resume: list[ResumeEntry | dict[str, Any]],
    ) -> RunHandle:
        payload = self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=_resume_body(resume)
        )
        res = TaskRunResponse.model_validate(payload)
        return RunHandle(None, res.run, self)

    def get(self, task_id: str, run_id: str) -> TaskRun:
        payload = self._http.request(
            "GET", f"/v1/tasks/{task_id}/runs/{run_id}"
        )
        return TaskRun.model_validate(payload)

    def cancel(
        self,
        task_id: str,
        run_id: str,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse:
        if options is not None:
            request = (
                options
                if isinstance(options, TaskCancelRequest)
                else TaskCancelRequest.model_validate(options)
            )
            return self._cancel_with(task_id, run_id, request)
        payload = self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs/{run_id}/cancel"
        )
        return TaskCancelResponse.model_validate(payload)

    def _cancel_with(
        self, task_id: str, run_id: str, request: TaskCancelRequest
    ) -> TaskCancelResponse:
        payload = self._http.request(
            "POST",
            f"/v1/tasks/{task_id}/runs/{run_id}/cancel",
            json=request.model_dump(exclude_none=True, mode="json"),
        )
        return TaskCancelResponse.model_validate(payload)

    def stream(
        self,
        task_id: str,
        run_id: str,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> Iterator[AGUIEvent]:
        """Stream a run's AG-UI events.

        The stream resumes **transparently** across a mid-turn disconnect
        (gateway idle-timeout, load-balancer recycle, network blip): it
        re-attaches with the SSE-standard ``Last-Event-ID`` so the server
        replays the frames the client missed, yielding a single gap-free
        ``AGUIEvent`` sequence (INT-252). It completes when the turn finishes
        and raises only once recovery is exhausted — no consumer-visible change
        from a plain stream. The keyword args tune the recovery bounds.
        """
        return stream_resumable(
            self._http,
            task_id,
            run_id,
            max_reconnects=max_reconnects,
            backoff=backoff,
            timeout=timeout,
        )


class Tasks:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http
        self.runs = TaskRuns(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        statuses: builtins.list[str] | None = None,
        modes: builtins.list[str] | None = None,
        require_automation_id: bool | None = None,
    ) -> Pager[Task, Paginated[Task]]:
        """List tasks. Iterate the returned :class:`Pager` to stream every
        task across pages, or call ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[Task]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            if statuses:
                params["statuses"] = statuses
            if modes:
                params["modes"] = modes
            if require_automation_id is not None:
                params["require_automation_id"] = require_automation_id
            payload = self._http.request("GET", "/v1/tasks", params=params)
            return Paginated[Task].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        title: str | None = None,
        prompt: str | None = None,
        mode: TaskMode | str = TaskMode.AGENT,
        system_id: str | None = None,
        repository_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
    ) -> TaskCreateResponse:
        body: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "mode": mode.value if isinstance(mode, TaskMode) else mode,
            "system_id": system_id,
            "repository_id": (
                str(repository_id) if repository_id is not None else None
            ),
            "metadata": metadata,
            "idle_timeout_seconds": idle_timeout_seconds,
            "fork_share_id": fork_share_id,
        }
        body = {k: v for k, v in body.items() if v is not None}
        payload = self._http.request("POST", "/v1/tasks", json=body)
        return TaskCreateResponse.model_validate(payload)

    def get(self, task_id: str) -> Task:
        payload = self._http.request("GET", f"/v1/tasks/{task_id}")
        return Task.model_validate(payload)

    def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        is_archived: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if is_archived is not None:
            body["is_archived"] = is_archived
        if metadata is not None:
            body["metadata"] = metadata
        payload = self._http.request(
            "PATCH", f"/v1/tasks/{task_id}", json=body
        )
        return Task.model_validate(payload)

    def delete(self, task_id: str) -> None:
        """Soft-delete a task. Requires ``tasks:delete`` scope.

        Note: dashboard-minted API keys (Tasks switch) do NOT grant
        ``tasks:delete`` per the PR #678 scope model. Calls will return
        ``IntrospectionAPIError(status_code=403)`` unless the caller
        holds a wildcard or explicitly-elevated key.
        """
        self._http.request("DELETE", f"/v1/tasks/{task_id}", expect="empty")

    def archive(self, task_id: str) -> None:
        self._http.request(
            "POST", f"/v1/tasks/{task_id}/archive", expect="empty"
        )

    def unarchive(self, task_id: str) -> None:
        self._http.request(
            "POST", f"/v1/tasks/{task_id}/unarchive", expect="empty"
        )

    def start(
        self,
        *,
        prompt: str,
        title: str | None = None,
        mode: TaskMode | str = TaskMode.AGENT,
        system_id: str | None = None,
        repository_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        idle_timeout_seconds: int | None = None,
    ) -> RunHandle:
        """Cursor-style sugar: create a task + return a handle on its initial run.

        Example:
            >>> run = runner.tasks.start(prompt="Summarize this repo")
            >>> print(run.text())
        """
        res = self.create(
            title=title,
            prompt=prompt,
            mode=mode,
            system_id=system_id,
            repository_id=repository_id,
            metadata=metadata,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        return RunHandle(res.task, res.run, self.runs)


class AsyncRunHandle:
    """Async twin of :class:`RunHandle`.

    Returned by ``AsyncTasks.start(...)`` and ``AsyncTaskRuns.create(...)``.
    ``await handle.stream()`` is replaced by ``async for ev in
    handle.stream()`` to iterate AG-UI events; ``await handle.text()``
    collects text frames; ``await handle.cancel()`` uses the default abort
    behavior and accepts typed options for explicit abort or drain cancellation.
    """

    def __init__(
        self,
        task: Task | None,
        run: TaskRun,
        runs: AsyncTaskRuns,
    ) -> None:
        self.task = task
        self.run = run
        self._runs = runs

    def stream(
        self,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> AsyncIterator[AGUIEvent]:
        return self._runs.stream(
            str(self.run.task_id),
            self.run.id,
            max_reconnects=max_reconnects,
            backoff=backoff,
            timeout=timeout,
        )

    async def cancel(
        self,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse:
        return await self._runs.cancel(
            str(self.run.task_id), self.run.id, options=options
        )

    async def text(self) -> str:
        out: list[str] = []
        async for ev in self.stream():
            if isinstance(ev, TextMessageContentEvent | TextMessageChunkEvent):
                out.append(str(ev.delta or ""))
        return "".join(out)


class AsyncTaskRuns:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    async def create(
        self,
        task_id: str,
        *,
        prompt: TaskPrompt | dict[str, Any] | None = None,
        message: str | None = None,
        kind: TaskRunKind | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncRunHandle:
        body: dict[str, Any] = {}
        if prompt is not None:
            body["prompt"] = (
                prompt.model_dump(exclude_none=True)
                if isinstance(prompt, TaskPrompt)
                else prompt
            )
        if message is not None:
            body["message"] = message
        if kind is not None:
            body["kind"] = (
                kind.value if isinstance(kind, TaskRunKind) else kind
            )
        if metadata is not None:
            body["metadata"] = metadata
        payload = await self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=body
        )
        res = TaskRunResponse.model_validate(payload)
        return AsyncRunHandle(None, res.run, self)

    async def resume(
        self,
        task_id: str,
        *,
        resume: list[ResumeEntry | dict[str, Any]],
    ) -> AsyncRunHandle:
        payload = await self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=_resume_body(resume)
        )
        res = TaskRunResponse.model_validate(payload)
        return AsyncRunHandle(None, res.run, self)

    async def get(self, task_id: str, run_id: str) -> TaskRun:
        payload = await self._http.request(
            "GET", f"/v1/tasks/{task_id}/runs/{run_id}"
        )
        return TaskRun.model_validate(payload)

    async def cancel(
        self,
        task_id: str,
        run_id: str,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse:
        if options is not None:
            request = (
                options
                if isinstance(options, TaskCancelRequest)
                else TaskCancelRequest.model_validate(options)
            )
            return await self._cancel_with(task_id, run_id, request)
        payload = await self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs/{run_id}/cancel"
        )
        return TaskCancelResponse.model_validate(payload)

    async def _cancel_with(
        self, task_id: str, run_id: str, request: TaskCancelRequest
    ) -> TaskCancelResponse:
        payload = await self._http.request(
            "POST",
            f"/v1/tasks/{task_id}/runs/{run_id}/cancel",
            json=request.model_dump(exclude_none=True, mode="json"),
        )
        return TaskCancelResponse.model_validate(payload)

    def stream(
        self,
        task_id: str,
        run_id: str,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> AsyncIterator[AGUIEvent]:
        """Stream a run's AG-UI events with transparent resume — async twin of
        :meth:`TaskRuns.stream`."""
        return stream_resumable_async(
            self._http,
            task_id,
            run_id,
            max_reconnects=max_reconnects,
            backoff=backoff,
            timeout=timeout,
        )


class AsyncTasks:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.runs = AsyncTaskRuns(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        statuses: builtins.list[str] | None = None,
        modes: builtins.list[str] | None = None,
        require_automation_id: bool | None = None,
    ) -> AsyncPager[Task, Paginated[Task]]:
        """List tasks. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every task across pages."""

        async def fetch(cursor: str | None) -> Paginated[Task]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            if statuses:
                params["statuses"] = statuses
            if modes:
                params["modes"] = modes
            if require_automation_id is not None:
                params["require_automation_id"] = require_automation_id
            payload = await self._http.request(
                "GET", "/v1/tasks", params=params
            )
            return Paginated[Task].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        title: str | None = None,
        prompt: str | None = None,
        mode: TaskMode | str = TaskMode.AGENT,
        system_id: str | None = None,
        repository_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
    ) -> TaskCreateResponse:
        body: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "mode": mode.value if isinstance(mode, TaskMode) else mode,
            "system_id": system_id,
            "repository_id": (
                str(repository_id) if repository_id is not None else None
            ),
            "metadata": metadata,
            "idle_timeout_seconds": idle_timeout_seconds,
            "fork_share_id": fork_share_id,
        }
        body = {k: v for k, v in body.items() if v is not None}
        payload = await self._http.request("POST", "/v1/tasks", json=body)
        return TaskCreateResponse.model_validate(payload)

    async def get(self, task_id: str) -> Task:
        payload = await self._http.request("GET", f"/v1/tasks/{task_id}")
        return Task.model_validate(payload)

    async def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        is_archived: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if is_archived is not None:
            body["is_archived"] = is_archived
        if metadata is not None:
            body["metadata"] = metadata
        payload = await self._http.request(
            "PATCH", f"/v1/tasks/{task_id}", json=body
        )
        return Task.model_validate(payload)

    async def delete(self, task_id: str) -> None:
        """Soft-delete a task. Requires ``tasks:delete`` scope.

        Note: dashboard-minted API keys (Tasks switch) do NOT grant
        ``tasks:delete`` per the PR #678 scope model. Calls will return
        ``IntrospectionAPIError(status_code=403)`` unless the caller
        holds a wildcard or explicitly-elevated key.
        """
        await self._http.request(
            "DELETE", f"/v1/tasks/{task_id}", expect="empty"
        )

    async def archive(self, task_id: str) -> None:
        await self._http.request(
            "POST", f"/v1/tasks/{task_id}/archive", expect="empty"
        )

    async def unarchive(self, task_id: str) -> None:
        await self._http.request(
            "POST", f"/v1/tasks/{task_id}/unarchive", expect="empty"
        )

    async def start(
        self,
        *,
        prompt: str,
        title: str | None = None,
        mode: TaskMode | str = TaskMode.AGENT,
        system_id: str | None = None,
        repository_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        idle_timeout_seconds: int | None = None,
    ) -> AsyncRunHandle:
        """Cursor-style sugar: create a task + return a handle on its initial
        run.

        Example:
            >>> run = await runner.tasks.start(prompt="Summarize this repo")
            >>> print(await run.text())
        """
        res = await self.create(
            title=title,
            prompt=prompt,
            mode=mode,
            system_id=system_id,
            repository_id=repository_id,
            metadata=metadata,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        return AsyncRunHandle(res.task, res.run, self.runs)
