"""`runner.tasks.*` namespace: tasks + runs + cursor-style sugar.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Iterator
from typing import Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelResponse,
    TaskCreateResponse,
    TaskMode,
    TaskPrompt,
    TaskRun,
    TaskRunResponse,
    TaskVisibility,
)
from introspection_sdk.streaming import SseEvent, parse_sse, parse_sse_async


class RunHandle:
    """Returned by ``Tasks.start(...)`` and ``TaskRuns.create(...)``.

    Mirrors the Cursor SDK shape: ``handle.stream()`` to iterate raw
    SSE events, ``handle.text()`` to collect text frames into a string,
    ``handle.cancel()`` to cancel the run.
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

    def stream(self) -> Iterator[SseEvent]:
        return self._runs.stream(str(self.run.task_id), self.run.id)

    def cancel(self) -> TaskCancelResponse:
        return self._runs.cancel(str(self.run.task_id), self.run.id)

    def text(self) -> str:
        out: list[str] = []
        for ev in self.stream():
            if ev.event in ("text", "message"):
                out.append(ev.data)
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
        payload = self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=body
        )
        res = TaskRunResponse.model_validate(payload)
        return RunHandle(None, res.run, self)

    def get(self, task_id: str, run_id: str) -> TaskRun:
        payload = self._http.request(
            "GET", f"/v1/tasks/{task_id}/runs/{run_id}"
        )
        return TaskRun.model_validate(payload)

    def cancel(self, task_id: str, run_id: str) -> TaskCancelResponse:
        payload = self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs/{run_id}/cancel"
        )
        return TaskCancelResponse.model_validate(payload)

    def stream(self, task_id: str, run_id: str) -> Iterator[SseEvent]:
        lines = self._http.stream_sse_lines(
            f"/v1/tasks/{task_id}/runs/{run_id}/stream"
        )
        yield from parse_sse(lines)


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
        repository_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        visibility: TaskVisibility | str | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
    ) -> TaskCreateResponse:
        body: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "mode": mode.value if isinstance(mode, TaskMode) else mode,
            "system_id": system_id,
            "repository_id": repository_id,
            "metadata": metadata,
            "visibility": (
                visibility.value
                if isinstance(visibility, TaskVisibility)
                else visibility
            ),
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
        repository_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        visibility: TaskVisibility | str | None = None,
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
            visibility=visibility,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        return RunHandle(res.task, res.run, self.runs)


class AsyncRunHandle:
    """Async twin of :class:`RunHandle`.

    Returned by ``AsyncTasks.start(...)`` and ``AsyncTaskRuns.create(...)``.
    ``await handle.stream()`` is replaced by ``async for ev in
    handle.stream()`` to iterate raw SSE events; ``await handle.text()``
    collects text frames; ``await handle.cancel()`` cancels the run.
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

    def stream(self) -> AsyncIterator[SseEvent]:
        return self._runs.stream(str(self.run.task_id), self.run.id)

    async def cancel(self) -> TaskCancelResponse:
        return await self._runs.cancel(str(self.run.task_id), self.run.id)

    async def text(self) -> str:
        out: list[str] = []
        async for ev in self.stream():
            if ev.event in ("text", "message"):
                out.append(ev.data)
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
        payload = await self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs", json=body
        )
        res = TaskRunResponse.model_validate(payload)
        return AsyncRunHandle(None, res.run, self)

    async def get(self, task_id: str, run_id: str) -> TaskRun:
        payload = await self._http.request(
            "GET", f"/v1/tasks/{task_id}/runs/{run_id}"
        )
        return TaskRun.model_validate(payload)

    async def cancel(self, task_id: str, run_id: str) -> TaskCancelResponse:
        payload = await self._http.request(
            "POST", f"/v1/tasks/{task_id}/runs/{run_id}/cancel"
        )
        return TaskCancelResponse.model_validate(payload)

    async def stream(
        self, task_id: str, run_id: str
    ) -> AsyncIterator[SseEvent]:
        lines = self._http.stream_sse_lines(
            f"/v1/tasks/{task_id}/runs/{run_id}/stream"
        )
        async for event in parse_sse_async(lines):
            yield event


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
        repository_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        visibility: TaskVisibility | str | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
    ) -> TaskCreateResponse:
        body: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "mode": mode.value if isinstance(mode, TaskMode) else mode,
            "system_id": system_id,
            "repository_id": repository_id,
            "metadata": metadata,
            "visibility": (
                visibility.value
                if isinstance(visibility, TaskVisibility)
                else visibility
            ),
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
        repository_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        visibility: TaskVisibility | str | None = None,
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
            visibility=visibility,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        return AsyncRunHandle(res.task, res.run, self.runs)
