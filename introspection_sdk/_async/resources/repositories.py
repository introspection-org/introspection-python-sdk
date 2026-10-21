"""Async twins re-exported by :mod:`introspection_sdk.resources.repositories`."""

from __future__ import annotations

import builtins
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.resources._repositories_common import (
    _CONTENT,
    _REPOSITORY_LIST,
    _commit_path,
    _commits_path,
    _contents_path,
    _directory,
    _merge,
    _merge_body,
    _merges_path,
    _pager_items,
    _pager_next,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.repositories import (
    Repository,
    RepositoryCommit,
    RepositoryCommitDetail,
    RepositoryDirectory,
    RepositoryEntry,
    RepositoryFile,
    RepositoryMerge,
)


class AsyncRepositoryContents:
    """DP ``/v1/repositories/{id}/contents`` namespace.

    Call it to enumerate a directory; use :meth:`get` for one page of a
    directory or a file's content.
    """

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


class AsyncRepositoryMerges:
    """DP ``/v1/repositories/{id}/merges`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    async def create(
        self,
        repository_id: UUID | str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> RepositoryMerge | None:
        """Merge ``head`` (a branch or a full commit sha) into ``base``.

        Returns the merge commit, or ``None`` when ``base`` already contains
        ``head``. A conflict raises :class:`ConflictError` with nothing
        changed. A merge still running after 60s raises
        :class:`SandboxUnavailableError`; calling again with the same
        ``base`` and ``head`` attaches to it. ``commit_message`` defaults
        server-side to ``Merge {head} into {base}``.
        """
        response = await self._http.request(
            "POST",
            _merges_path(repository_id),
            json=_merge_body(base, head, commit_message),
            expect="raw",
        )
        return _merge(response)


class AsyncRepositories:
    """CP ``/v1/repositories`` namespace, plus DP :attr:`contents`,
    commits and :attr:`merges`."""

    contents: AsyncRepositoryContents
    merges: AsyncRepositoryMerges

    def __init__(
        self, http: _AsyncHttpClient, dp_http: _AsyncHttpClient
    ) -> None:
        self._http = http
        self._dp_http = dp_http
        self.contents = AsyncRepositoryContents(dp_http)
        self.merges = AsyncRepositoryMerges(dp_http)

    async def list(
        self,
        *,
        project: str | UUID | None = None,
        slug: str | None = None,
    ) -> builtins.list[Repository]:
        """The repositories linked to the project.

        ``slug`` narrows to one: ``owner/repo`` for GitHub, the Runtime slug
        for a hosted repository.
        """
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

    def commits(
        self,
        repository_id: UUID | str,
        sha: str | None = None,
        path: str | None = None,
        limit: int | None = None,
    ) -> AsyncPager[RepositoryCommit, Paginated[RepositoryCommit]]:
        """The history from ``sha`` (a branch, tag or commit; the default
        branch when omitted) across pages, narrowed to commits touching
        ``path`` when set."""

        async def fetch(cursor: str | None) -> Paginated[RepositoryCommit]:
            payload = await self._dp_http.request(
                "GET",
                _commits_path(repository_id),
                params={
                    "sha": sha,
                    "path": path,
                    "cursor": cursor,
                    "limit": limit,
                },
            )
            return Paginated[RepositoryCommit].model_validate(payload)

        return async_cursor_paginate(fetch)

    async def commit(
        self, repository_id: UUID | str, sha: str
    ) -> RepositoryCommitDetail:
        """One commit with its changed files and unified diff."""
        payload = await self._dp_http.request(
            "GET", _commit_path(repository_id, sha)
        )
        return RepositoryCommitDetail.model_validate(payload)
