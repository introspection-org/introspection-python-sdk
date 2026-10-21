"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.tasks`."""

from __future__ import annotations

from typing import Any

from introspection_sdk.schemas.agui import (
    AssistantMessage,
    MessagesSnapshotEvent,
    ResumeEntry,
)
from introspection_sdk.schemas.tasks import (
    TaskFileRef,
    TaskRepoRequest,
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


def _snapshot_text(event: MessagesSnapshotEvent) -> list[str]:
    """A snapshot carries the whole run so far, so it replaces what was read."""
    return [
        m.content
        for m in event.messages
        if isinstance(m, AssistantMessage) and isinstance(m.content, str)
    ]
