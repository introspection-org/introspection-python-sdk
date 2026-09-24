"""``client.repositories`` — repository lookup (CP) and contents (DP).

Read-only: a runner resolves the repository behind the recipe it runs, it
does not register one. Linking a repository to a project is a
project-authoring act and lives in the CLI.

Unlike the other CP lists, ``GET /v1/repositories`` answers a bare JSON
array rather than the cursor envelope, so :meth:`Repositories.list` returns
a ``list``. Contents are read on the data plane, which resolves ``ref`` to
one commit and reads every page of a listing at it.
"""

from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import quote
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import AsyncPager, Pager
from introspection_sdk.schemas.repositories import (
    Repository,
    RepositoryContent,
    RepositoryDirectory,
    RepositoryEntry,
    RepositoryFile,
)

_REPOSITORY_LIST = TypeAdapter(list[Repository])
_CONTENT = TypeAdapter(RepositoryContent)


def _contents_path(repository_id: UUID | str, path: str) -> str:
    """Percent-encode each segment; ``/`` stays literal. Empty is the root."""
    base = f"/v1/repositories/{repository_id}/contents"
    segments = [quote(s, safe="") for s in path.strip("/").split("/") if s]
    return f"{base}/{'/'.join(segments)}" if segments else base


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


class RepositoryContents:
    """DP ``/v1/repositories/{id}/contents`` namespace.

    Call it to enumerate a directory; use :meth:`get` for one page of a
    directory or a file's content.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def __call__(
        self,
        repository_id: UUID | str,
        path: str = "",
        ref: str | None = None,
        limit: int | None = None,
    ) -> Pager[RepositoryEntry, RepositoryDirectory]:
        """List a directory's entries across pages.

        Iterating raises :class:`ValueError` when ``path`` is a file.
        """

        def fetch(cursor: str | None) -> RepositoryDirectory:
            payload = self._http.request(
                "GET",
                _contents_path(repository_id, path),
                params={"ref": ref, "cursor": cursor, "limit": limit},
            )
            return _directory(payload, path)

        return Pager(fetch, items=_pager_items, next_cursor=_pager_next)

    def get(
        self,
        repository_id: UUID | str,
        path: str = "",
        ref: str | None = None,
    ) -> RepositoryDirectory | RepositoryFile:
        """A directory's first page or a file's content, discriminated on
        ``type``."""
        payload = self._http.request(
            "GET",
            _contents_path(repository_id, path),
            params={"ref": ref},
        )
        return _CONTENT.validate_python(payload)


class Repositories:
    """CP ``/v1/repositories`` namespace, plus DP :attr:`contents`."""

    contents: RepositoryContents

    def __init__(self, http: _HttpClient, dp_http: _HttpClient) -> None:
        self._http = http
        self.contents = RepositoryContents(dp_http)

    def list(
        self,
        *,
        project: str | UUID | None = None,
        slug: str | None = None,
    ) -> builtins.list[Repository]:
        """The repositories linked to the project.

        ``slug`` narrows to one: ``owner/repo`` for GitHub, the Runtime slug
        for a hosted repository.
        """
        payload = self._http.request(
            "GET",
            "/v1/repositories",
            params={"project": project, "slug": slug},
        )
        return _REPOSITORY_LIST.validate_python(payload)

    def get(
        self,
        repository_id: UUID | str,
        *,
        project: str | UUID | None = None,
    ) -> Repository:
        payload = self._http.request(
            "GET",
            f"/v1/repositories/{repository_id}",
            params={"project": project},
        )
        return Repository.model_validate(payload)


class AsyncRepositoryContents:
    """Async twin of :class:`RepositoryContents`."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def __call__(
        self,
        repository_id: UUID | str,
        path: str = "",
        ref: str | None = None,
        limit: int | None = None,
    ) -> AsyncPager[RepositoryEntry, RepositoryDirectory]:
        """List a directory's entries across pages.

        Iterating raises :class:`ValueError` when ``path`` is a file.
        """

        async def fetch(cursor: str | None) -> RepositoryDirectory:
            payload = await self._http.request(
                "GET",
                _contents_path(repository_id, path),
                params={"ref": ref, "cursor": cursor, "limit": limit},
            )
            return _directory(payload, path)

        return AsyncPager(fetch, items=_pager_items, next_cursor=_pager_next)

    async def get(
        self,
        repository_id: UUID | str,
        path: str = "",
        ref: str | None = None,
    ) -> RepositoryDirectory | RepositoryFile:
        """A directory's first page or a file's content, discriminated on
        ``type``."""
        payload = await self._http.request(
            "GET",
            _contents_path(repository_id, path),
            params={"ref": ref},
        )
        return _CONTENT.validate_python(payload)


class AsyncRepositories:
    """Async twin of :class:`Repositories`."""

    contents: AsyncRepositoryContents

    def __init__(
        self, http: _AsyncHttpClient, dp_http: _AsyncHttpClient
    ) -> None:
        self._http = http
        self.contents = AsyncRepositoryContents(dp_http)

    async def list(
        self,
        *,
        project: str | UUID | None = None,
        slug: str | None = None,
    ) -> builtins.list[Repository]:
        """Async twin of :meth:`Repositories.list`."""
        payload = await self._http.request(
            "GET",
            "/v1/repositories",
            params={"project": project, "slug": slug},
        )
        return _REPOSITORY_LIST.validate_python(payload)

    async def get(
        self,
        repository_id: UUID | str,
        *,
        project: str | UUID | None = None,
    ) -> Repository:
        payload = await self._http.request(
            "GET",
            f"/v1/repositories/{repository_id}",
            params={"project": project},
        )
        return Repository.model_validate(payload)


__all__ = [
    "AsyncRepositories",
    "AsyncRepositoryContents",
    "Repositories",
    "RepositoryContents",
]
