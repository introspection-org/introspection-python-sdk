"""Async twins re-exported by :mod:`introspection_sdk.runner_resources.files`."""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator
from typing import Any

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.runner_resources._files_common import (
    FileLike,
    _materialise_upload,
    _upload_form,
)
from introspection_sdk.schemas.files import (
    File,
    FileCreateTextRequest,
    FileType,
    FileUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


class AsyncFileVersions:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        file_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
    ) -> AsyncPager[File, Paginated[File]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List versions of a file. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every version across pages."""
        # unasync: end
        """List versions of a file. Iterate the returned :class:`Pager` to
        stream every version across pages, or call ``.page()`` for the
        first page only."""

        async def fetch(cursor: str | None) -> Paginated[File]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            payload = await self._http.request(
                "GET", f"/v1/files/{file_id}/versions", params=params
            )
            return Paginated[File].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, file_id: str, version_id: str) -> File:
        payload = await self._http.request(
            "GET", f"/v1/files/{file_id}/versions/{version_id}"
        )
        return File.model_validate(payload)

    async def create(
        self,
        file_id: str,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
    ) -> File:
        with _materialise_upload(file, name, content_type) as (
            n,
            body,
            ct,
        ):
            files = {"file": (n, body, ct)}
            data = {
                "name": n,
                "file_type": (
                    file_type.value
                    if isinstance(file_type, FileType)
                    else file_type
                ),
            }
            payload = await self._http.request(
                "POST",
                f"/v1/files/{file_id}/versions",
                files=files,
                data=data,
            )
        return File.model_validate(payload)


class AsyncFiles:
    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.versions = AsyncFileVersions(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        name: str | None = None,
        file_type: FileType | str | None = None,
        storage_path: str | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AsyncPager[File, Paginated[File]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List files. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every file across pages.

        ``metadata`` narrows to files whose metadata holds every pair, each
        matched exactly against the string value; it is sent as one repeated
        ``metadata=key:value`` param per entry (at most 16). Keys are letters,
        digits, ``_`` and ``-``. A server that predates the filter ignores it
        and returns the unfiltered list."""
        # unasync: end
        """List files. Iterate the returned :class:`Pager` to stream every
        file across pages, or call ``.page()`` for the first page only.

        ``metadata`` narrows to files whose metadata holds every pair, each
        matched exactly against the string value; it is sent as one repeated
        ``metadata=key:value`` param per entry (at most 16). Keys are letters,
        digits, ``_`` and ``-``. A server that predates the filter ignores it
        and returns the unfiltered list."""

        async def fetch(cursor: str | None) -> Paginated[File]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
                "name": name,
                "file_type": (
                    file_type.value
                    if isinstance(file_type, FileType)
                    else file_type
                ),
                "storage_path": storage_path,
                "tag": tag,
                "metadata": (
                    [f"{key}:{value}" for key, value in metadata.items()]
                    if metadata
                    else None
                ),
            }
            payload = await self._http.request(
                "GET", "/v1/files", params=params
            )
            return Paginated[File].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def upload(
        self,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File:
        # unasync: async-only (the sync twin's docstring follows)
        """Upload a binary file via multipart.

        ``tags`` and ``metadata`` are stamped when the request creates the
        file. A request that adds a new version to an existing file keeps
        that file's tags; change them with :meth:`update`.

        Example:
            >>> await runner.files.upload(
            ...     file=Path("input.jsonl"),
            ...     file_type="upload",
            ... )
        """
        # unasync: end
        """Upload a binary file via multipart.

        ``tags`` and ``metadata`` are stamped when the request creates the
        file. A request that adds a new version to an existing file keeps
        that file's tags; change them with :meth:`update`.

        Example:
            >>> runner.files.upload(
            ...     file=Path("input.jsonl"),
            ...     file_type="upload",
            ... )
        """
        with _materialise_upload(file, name, content_type) as (
            n,
            body,
            ct,
        ):
            files = {"file": (n, body, ct)}
            data = _upload_form(n, file_type, metadata, tags)
            payload = await self._http.request(
                "POST", "/v1/files", files=files, data=data
            )
        return File.model_validate(payload)

    async def create_text(
        self,
        *,
        name: str,
        content: str,
        mime_type: str = "text/markdown",
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File:
        """Create a text/markdown file via JSON body.

        ``tags`` and ``metadata`` are stamped when the request creates the
        file. A request that adds a new version to an existing file keeps
        that file's tags; change them with :meth:`update`."""
        body = FileCreateTextRequest(
            name=name,
            content=content,
            mime_type=mime_type,
            metadata=metadata,
            tags=tags,
        )
        payload = await self._http.request(
            "POST", "/v1/files", json=body.model_dump(exclude_none=True)
        )
        return File.model_validate(payload)

    async def get(self, file_id: str) -> File:
        payload = await self._http.request("GET", f"/v1/files/{file_id}")
        return File.model_validate(payload)

    async def update(
        self,
        file_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File:
        # `exclude_none` drops an omitted tag list but keeps an explicit [],
        # which is what clears the tags — they replace wholesale.
        body = FileUpdateRequest(
            name=name, metadata=metadata, tags=tags
        ).model_dump(exclude_none=True)
        payload = await self._http.request(
            "PATCH", f"/v1/files/{file_id}", json=body
        )
        return File.model_validate(payload)

    async def delete(self, file_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/files/{file_id}", expect="empty"
        )

    async def download(self, file_id: str) -> bytes:
        return await self._http.request(
            "GET", f"/v1/files/{file_id}/content", expect="bytes"
        )

    def download_stream(self, file_id: str) -> AsyncIterator[bytes]:
        return self._http.stream_bytes(f"/v1/files/{file_id}/content")
