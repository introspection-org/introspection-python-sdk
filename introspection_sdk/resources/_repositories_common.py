"""Code shared by the sync and async twins in :mod:`introspection_sdk.resources.repositories`."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk._http import RawResponse
from introspection_sdk.schemas.repositories import (
    Repository,
    RepositoryContent,
    RepositoryDirectory,
    RepositoryEntry,
    RepositoryFile,
    RepositoryMerge,
)

_REPOSITORY_LIST = TypeAdapter(list[Repository])


_CONTENT = TypeAdapter(RepositoryContent)


def _contents_path(repository_id: UUID | str, path: str) -> str:
    """Percent-encode each segment; ``/`` stays literal. Empty is the root."""
    base = f"/v1/repositories/{repository_id}/contents"
    segments = [quote(s, safe="") for s in path.strip("/").split("/") if s]
    return f"{base}/{'/'.join(segments)}" if segments else base


def _commits_path(repository_id: UUID | str) -> str:
    return f"/v1/repositories/{repository_id}/commits"


def _commit_path(repository_id: UUID | str, sha: str) -> str:
    return f"{_commits_path(repository_id)}/{quote(sha, safe='')}"


def _merges_path(repository_id: UUID | str) -> str:
    return f"/v1/repositories/{repository_id}/merges"


def _merge_body(
    base: str, head: str, commit_message: str | None
) -> dict[str, str]:
    body = {"base": base, "head": head}
    if commit_message is not None:
        body["commit_message"] = commit_message
    return body


def _merge(response: RawResponse) -> RepositoryMerge | None:
    """``None`` on 204: ``base`` already contains ``head``."""
    if not response.content:
        return None
    return RepositoryMerge.model_validate_json(response.content)


def _directory(payload: Any, path: str) -> RepositoryDirectory:
    content = _CONTENT.validate_python(payload)
    if isinstance(content, RepositoryFile):
        raise ValueError(
            f"{path!r} is a file, not a directory; read it with "
            "repositories.contents.get()"
        )
    return content


def _pager_items(page: RepositoryDirectory) -> list[RepositoryEntry]:
    return page.records


def _pager_next(page: RepositoryDirectory) -> str | None:
    return page.next
