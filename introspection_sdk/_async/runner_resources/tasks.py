"""Re-exported by :mod:`introspection_sdk.runner_resources.tasks`."""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from introspection_sdk._errors import RunFailedError, StreamIncompleteError
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.resumable import (
    stream_resumable_async,
)
from introspection_sdk.schemas.agui import (
    AGUIEvent,
    AssistantMessage,
    CustomEvent,
    MessagesSnapshotEvent,
    ResumeEntry,
    RunErrorEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.task_commands import (
    TASK_COMMAND_SPEC_ADAPTER,
    DownloadCommand,
    ExecCommand,
    TaskCommand,
    TaskCommandStatus,
    UploadCommand,
)
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelRequest,
    TaskCancelResponse,
    TaskCreateResponse,
    TaskFileRef,
    TaskKind,
    TaskPrompt,
    TaskRepoRequest,
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


def _file_refs(
    files: list[TaskFileRef | dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        ref.model_dump(exclude_none=True)
        if isinstance(ref, TaskFileRef)
        else ref
        for ref in files
    ]


def _repo_refs(
    repositories: list[TaskRepoRequest | dict[str, Any]],
) -> list[dict[str, Any]]:
    # `exclude_none` matters here: `ref` and `depth` default to the
    # repository's registered branch and a shallow clone server-side, and a
    # null would be the caller asking for something instead of nothing.
    return [
        repo.model_dump(exclude_none=True)
        if isinstance(repo, TaskRepoRequest)
        else repo
        for repo in repositories
    ]


#: The longest :meth:`TaskCommands.get` asks the API to hold a read. The API
#: allows 60 seconds, but it has to answer inside the SDK's own 30-second
#: request timeout, or the read fails instead of returning the command.
MAX_COMMAND_WAIT_SECONDS = 25


def _snapshot_text(event: MessagesSnapshotEvent) -> list[str]:
    """A snapshot carries the whole run so far, so it replaces what was read."""
    return [
        m.content
        for m in event.messages
        if isinstance(m, AssistantMessage) and isinstance(m.content, str)
    ]


class AsyncRunHandle:
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`RunHandle`.

    Returned by ``AsyncTasks.start(...)`` and ``AsyncTaskRuns.create(...)``.
    ``await handle.stream()`` is replaced by ``async for ev in
    handle.stream()`` to iterate AG-UI events; ``await handle.text()``
    collects text frames; ``await handle.cancel()`` uses the default abort
    behavior and accepts typed options for explicit abort or drain cancellation.
    """

    # unasync: end
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
        """Stream this run's AG-UI events, reconnecting on a dropped
        connection under the recovery contract in
        :mod:`introspection_sdk.resumable`."""
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
        """Collect this run's assistant text from :meth:`stream`.

        Never returns partial output: raises ``RunFailedError`` on
        ``RUN_ERROR`` and ``StreamIncompleteError`` wherever output may be
        missing (a ``410``, a ``resume_gap``, or a run that settled without
        the stream confirming it). A ``MESSAGES_SNAPSHOT`` replaces the text
        collected so far with the snapshot's. The transcript is not read to
        fill a gap, so streaming needs no ``conversations:read`` scope; read
        ``runner.conversations`` yourself when you need the output after
        such an error.
        """
        out: list[str] = []
        async for ev in self.stream():
            if isinstance(ev, RunErrorEvent):
                raise RunFailedError(ev.message, code=ev.code)
            if isinstance(ev, CustomEvent) and ev.name == "resume_gap":
                raise StreamIncompleteError(
                    "The replay buffer lost output; read the conversation transcript"
                )
            if isinstance(ev, MessagesSnapshotEvent):
                out = _snapshot_text(ev)
            elif isinstance(
                ev, TextMessageContentEvent | TextMessageChunkEvent
            ):
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
        kind: TaskRunKind | str | None = None,
        metadata: dict[str, Any] | None = None,
        files: list[TaskFileRef | dict[str, Any]] | None = None,
    ) -> AsyncRunHandle:
        body: dict[str, Any] = {}
        if prompt is not None:
            body["prompt"] = (
                prompt.model_dump(exclude_none=True)
                if isinstance(prompt, TaskPrompt)
                else prompt
            )
        if kind is not None:
            body["kind"] = (
                kind.value if isinstance(kind, TaskRunKind) else kind
            )
        if metadata is not None:
            body["metadata"] = metadata
        if files:
            body["files"] = _file_refs(files)
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
        # unasync: async-only (the sync twin's docstring follows)
        """Stream a run's AG-UI events with transparent resume — async twin of
        :meth:`TaskRuns.stream`."""
        # unasync: end
        """Stream a run's AG-UI events, reconnecting on a dropped connection
        under the recovery contract in :mod:`introspection_sdk.resumable`.
        The keyword args bound recovery attempts."""
        return stream_resumable_async(
            self._http,
            task_id,
            run_id,
            max_reconnects=max_reconnects,
            backoff=backoff,
            timeout=timeout,
        )


class AsyncTaskCommands:
    """DP ``/v1/tasks/{task_id}/commands``: ``exec``, ``upload`` and
    ``download`` against an eval task's live sandbox.

    A command is a row the task's workflow executes and stamps: the create
    returns it ``queued``, and :meth:`get` reads its outcome, optionally
    holding the read until it finishes. Eval tasks only (create the task
    with ``kind="eval"`` and ``commands=True``), behind ``tasks:exec``, on a
    plane with evals enabled.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    async def create(
        self,
        task_id: str,
        command: ExecCommand
        | UploadCommand
        | DownloadCommand
        | dict[str, Any],
    ) -> TaskCommand:
        """Record a command and send it to the task's workflow. ``command``
        is an :class:`ExecCommand`, :class:`UploadCommand` or
        :class:`DownloadCommand` (or the same as a dict tagged by
        ``kind``)."""
        spec = TASK_COMMAND_SPEC_ADAPTER.validate_python(command)
        payload = await self._http.request(
            "POST",
            f"/v1/tasks/{task_id}/commands",
            json=spec.model_dump(mode="json", exclude_none=True),
        )
        return TaskCommand.model_validate(payload)

    def list(
        self,
        task_id: str,
        *,
        status: TaskCommandStatus | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[TaskCommand, Paginated[TaskCommand]]:
        """List a task's commands, newest first, across pages."""

        async def fetch(cursor: str | None) -> Paginated[TaskCommand]:
            payload = await self._http.request(
                "GET",
                f"/v1/tasks/{task_id}/commands",
                params={
                    "status": str(status) if status is not None else None,
                    "limit": limit,
                    "next": cursor,
                },
            )
            return Paginated[TaskCommand].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(
        self,
        task_id: str,
        command_id: str | UUID,
        *,
        wait_seconds: int | None = None,
    ) -> TaskCommand:
        """Read a command. ``wait_seconds`` holds the read until the command
        finishes or the wait runs out, and returns it in whatever state it
        is then; it is capped at :data:`MAX_COMMAND_WAIT_SECONDS`, so call
        again to wait longer."""
        if wait_seconds is not None:
            wait_seconds = max(0, min(wait_seconds, MAX_COMMAND_WAIT_SECONDS))
        payload = await self._http.request(
            "GET",
            f"/v1/tasks/{task_id}/commands/{command_id}",
            params={"wait_seconds": wait_seconds},
        )
        return TaskCommand.model_validate(payload)


class AsyncTasks:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.runs = AsyncTaskRuns(http)
        self.commands = AsyncTaskCommands(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        statuses: builtins.list[str] | None = None,
        require_automation_id: bool | None = None,
        tag: str | None = None,
    ) -> AsyncPager[Task, Paginated[Task]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List tasks. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every task across pages."""
        # unasync: end
        """List tasks. Iterate the returned :class:`Pager` to stream every
        task across pages, or call ``.page()`` for the first page only."""

        async def fetch(cursor: str | None) -> Paginated[Task]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
                "tag": tag,
            }
            if statuses:
                params["statuses"] = statuses
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
        agent_name: str | None = None,
        repositories: builtins.list[TaskRepoRequest | dict[str, Any]]
        | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_metadata: dict[str, str] | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
        files: builtins.list[TaskFileRef | dict[str, Any]] | None = None,
        tags: builtins.list[str] | None = None,
        kind: TaskKind | str | None = None,
        commands: bool | None = None,
        compose: dict[str, Any] | None = None,
        recipe_git_commit_sha: str | None = None,
        runtime_id: UUID | str | None = None,
    ) -> TaskCreateResponse:
        """Create a task and its initial run.

        ``kind="eval"`` runs the task as an evaluation trial; with
        ``commands=True`` it also accepts :attr:`commands` against its live
        sandbox, ``compose`` runs services beside it, and
        ``recipe_git_commit_sha`` pins the Recipe commit it runs.
        ``runtime_id`` names the Runtime for a caller whose credential is not
        bound to one (a member token rather than a runner). Each is omitted
        from the body unless given.
        """
        body: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "agent_name": agent_name,
            "metadata": metadata,
            "conversation_metadata": conversation_metadata,
            "idle_timeout_seconds": idle_timeout_seconds,
            "fork_share_id": fork_share_id,
            "files": _file_refs(files) if files else None,
            "repositories": _repo_refs(repositories) if repositories else None,
            "tags": tags,
            "kind": str(kind) if kind is not None else None,
            "commands": commands,
            "compose": compose,
            "recipe_git_commit_sha": recipe_git_commit_sha,
            "runtime_id": str(runtime_id) if runtime_id is not None else None,
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
        tags: builtins.list[str] | None = None,
    ) -> Task:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if is_archived is not None:
            body["is_archived"] = is_archived
        if metadata is not None:
            body["metadata"] = metadata
        if tags is not None:
            # Replaces wholesale, so an explicit [] must reach the wire to
            # clear — `if tags:` would silently drop it.
            body["tags"] = tags
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

    async def start(self, *, prompt: str, **kwargs: Any) -> AsyncRunHandle:
        # unasync: async-only (the sync twin's docstring follows)
        """Cursor-style sugar: create a task + return a handle on its initial
        run.

        Takes everything :meth:`create` takes, with ``prompt`` required —
        ``start`` exists to stream a turn, and a task with no prompt has no
        turn to stream. Forwarding ``**kwargs`` rather than restating the
        parameters is deliberate: a hand-copied subset silently drops every
        field added to ``create`` afterwards, which is how ``fork_share_id``
        and ``tags`` became unreachable from here.

        Example:
            >>> run = await runner.tasks.start(prompt="Summarize this repo")
            >>> print(await run.text())
        """
        # unasync: end
        """Cursor-style sugar: create a task + return a handle on its initial run.

        Takes everything :meth:`create` takes, with ``prompt`` required —
        ``start`` exists to stream a turn, and a task with no prompt has no
        turn to stream. Forwarding ``**kwargs`` rather than restating the
        parameters is deliberate: a hand-copied subset silently drops every
        field added to ``create`` afterwards, which is how ``fork_share_id``
        and ``tags`` became unreachable from here.

        Example:
            >>> run = runner.tasks.start(prompt="Summarize this repo")
            >>> print(run.text())
        """
        res = await self.create(prompt=prompt, **kwargs)
        return AsyncRunHandle(res.task, res.run, self.runs)
