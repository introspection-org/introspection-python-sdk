"""Re-exported by :mod:`introspection_sdk.resources.repositories`."""

from __future__ import annotations

import builtins
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk._async.resources._crud import _body, _project
from introspection_sdk._http import RawResponse, _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.repositories import (
    HostedRepositoryCreate,
    Repository,
    RepositoryAccessGrant,
    RepositoryBranch,
    RepositoryCommit,
    RepositoryCommitDetail,
    RepositoryContent,
    RepositoryDirectory,
    RepositoryEntry,
    RepositoryFile,
    RepositoryMerge,
)

REPOSITORY_LIST = TypeAdapter(list[Repository])
CONTENT = TypeAdapter(RepositoryContent)


def _contents_path(repository_id: UUID | str, path: str) -> str:
    """Percent-encode each segment; ``/`` stays literal. Empty is the root."""
    base = f"/v1/repositories/{repository_id}/contents"
    segments = [quote(s, safe="") for s in path.strip("/").split("/") if s]
    return f"{base}/{'/'.join(segments)}" if segments else base


def _commits_path(repository_id: UUID | str) -> str:
    return f"/v1/repositories/{repository_id}/commits"


def _branches_path(repository_id: UUID | str) -> str:
    return f"/v1/repositories/{repository_id}/branches"


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
    content = CONTENT.validate_python(payload)
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
        return CONTENT.validate_python(payload)


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
        return REPOSITORY_LIST.validate_python(payload)

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

    async def create(
        self,
        slug: str,
        *,
        project: str | UUID | None = None,
        default_branch: str | None = None,
        seed_template: str | None = None,
    ) -> Repository:
        """Create a hosted repository, served over the platform's own Git
        transport at :attr:`Repository.url`.

        It starts ``provisioning_status="pending"``; poll :meth:`get` until
        it is ``ready``. Provisioning seeds it from ``seed_template`` (a
        template the deployment ships), or the deployment's default.
        """
        body = _body(
            HostedRepositoryCreate,
            {
                "slug": slug,
                "default_branch": default_branch,
                "seed_template": seed_template,
            },
        )
        payload = await self._http.request(
            "POST", "/v1/repositories", params=_project(project), json=body
        )
        return Repository.model_validate(payload)

    async def delete(
        self,
        repository_id: UUID | str,
        *,
        project: str | UUID | None = None,
    ) -> None:
        """Unlink a repository from the project; delete its recipes first."""
        await self._http.request(
            "DELETE",
            f"/v1/repositories/{repository_id}",
            params=_project(project),
            expect="empty",
        )

    def branches(
        self,
        repository_id: UUID | str,
        q: str | None = None,
        sort: Literal["name", "recent"] | None = None,
        limit: int | None = None,
    ) -> AsyncPager[RepositoryBranch, Paginated[RepositoryBranch]]:
        """The repository's branches across pages, by name; ``q`` keeps
        those whose name contains it, ignoring case. ``sort="recent"``
        dates each page's branches by their head commit."""

        async def fetch(cursor: str | None) -> Paginated[RepositoryBranch]:
            payload = await self._dp_http.request(
                "GET",
                _branches_path(repository_id),
                params={
                    "q": q,
                    "sort": sort,
                    "cursor": cursor,
                    "limit": limit,
                },
            )
            return Paginated[RepositoryBranch].model_validate(payload)

        return async_cursor_paginate(fetch)

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

    async def access_token(
        self,
        repository_id: UUID | str,
        *,
        permissions: dict[str, str] | None = None,
    ) -> RepositoryAccessGrant:
        """Mint a short-lived token for the repository's Git provider (DP
        ``POST /v1/repositories/{id}/access-token``).

        What it may reach is the runtime's grant, read from the caller's
        verified claims, so only a sandbox's token gets one; any other
        caller is refused. ``permissions`` narrows the token, e.g.
        ``{"contents": "read"}``."""
        payload = await self._dp_http.request(
            "POST",
            f"/v1/repositories/{repository_id}/access-token",
            json={"permissions": permissions or {}},
        )
        return RepositoryAccessGrant.model_validate(payload)


__all__ = [
    "AsyncRepositories",
    "AsyncRepositoryContents",
    "AsyncRepositoryMerges",
]
