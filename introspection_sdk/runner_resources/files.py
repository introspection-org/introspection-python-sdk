"""`runner.files.*` namespace: list / upload / download / versions.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

import builtins
import contextlib
import json
import mimetypes
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import IO, Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.files import (
    File,
    FileCreateTextRequest,
    FileType,
    FileUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated

FileLike = Path | IO[bytes] | bytes


@contextlib.contextmanager
def _materialise_upload(
    file: FileLike,
    name: str | None,
    content_type: str | None,
) -> Iterator[tuple[str, IO[bytes] | bytes, str]]:
    """Yield the multipart tuple for ``file``, closing anything it opened.

    A context manager because the ``Path`` branch opens a handle that used to
    be handed to httpx and never closed -- one leaked descriptor per upload,
    and one that stays open if the request raises.
    """
    if isinstance(file, Path):
        guessed_name = name or file.name
        guessed_ct = (
            content_type
            or mimetypes.guess_type(guessed_name)[0]
            or "application/octet-stream"
        )
        with file.open("rb") as handle:
            yield guessed_name, handle, guessed_ct
        return
    if isinstance(file, bytes | bytearray):
        if not name:
            raise ValueError("`name` is required when uploading raw bytes")
        ct = content_type or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        yield name, bytes(file), ct
        return
    # file-like object
    if not name:
        raise ValueError(
            "`name` is required when uploading a file-like object"
        )
    ct = content_type or (
        mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    yield name, file, ct


def _upload_form(
    name: str,
    file_type: FileType | str,
    metadata: dict[str, Any] | None,
    tags: list[str] | None,
) -> dict[str, Any]:
    """Build the multipart form fields for ``POST /v1/files``.

    ``tags`` goes out as one ``tags`` field per tag; ``metadata`` as a JSON
    object string. Either is left off the form entirely when ``None``.
    """
    data: dict[str, Any] = {
        "name": name,
        "file_type": (
            file_type.value if isinstance(file_type, FileType) else file_type
        ),
    }
    if metadata is not None:
        data["metadata"] = json.dumps(metadata)
    if tags is not None:
        data["tags"] = tags
    return data


class FileVersions:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        file_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
    ) -> Pager[File, Paginated[File]]:
        """List versions of a file. Iterate the returned :class:`Pager` to
        stream every version across pages, or call ``.page()`` for the
        first page only."""

        def fetch(cursor: str | None) -> Paginated[File]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
            }
            payload = self._http.request(
                "GET", f"/v1/files/{file_id}/versions", params=params
            )
            return Paginated[File].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(self, file_id: str, version_id: str) -> File:
        payload = self._http.request(
            "GET", f"/v1/files/{file_id}/versions/{version_id}"
        )
        return File.model_validate(payload)

    def create(
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
            payload = self._http.request(
                "POST",
                f"/v1/files/{file_id}/versions",
                files=files,
                data=data,
            )
        return File.model_validate(payload)


class Files:
    def __init__(self, http: _HttpClient) -> None:
        self._http = http
        self.versions = FileVersions(http)

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
    ) -> Pager[File, Paginated[File]]:
        """List files. Iterate the returned :class:`Pager` to stream every
        file across pages, or call ``.page()`` for the first page only.

        ``metadata`` narrows to files whose metadata holds every pair, each
        matched exactly against the string value; it is sent as one repeated
        ``metadata=key:value`` param per entry (at most 16). Keys are letters,
        digits, ``_`` and ``-``. A server that predates the filter ignores it
        and returns the unfiltered list."""

        def fetch(cursor: str | None) -> Paginated[File]:
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
            payload = self._http.request("GET", "/v1/files", params=params)
            return Paginated[File].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def upload(
        self,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File:
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
            payload = self._http.request(
                "POST", "/v1/files", files=files, data=data
            )
        return File.model_validate(payload)

    def create_text(
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
        payload = self._http.request(
            "POST", "/v1/files", json=body.model_dump(exclude_none=True)
        )
        return File.model_validate(payload)

    def get(self, file_id: str) -> File:
        payload = self._http.request("GET", f"/v1/files/{file_id}")
        return File.model_validate(payload)

    def update(
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
        payload = self._http.request(
            "PATCH", f"/v1/files/{file_id}", json=body
        )
        return File.model_validate(payload)

    def delete(self, file_id: str) -> None:
        self._http.request("DELETE", f"/v1/files/{file_id}", expect="empty")

    def download(self, file_id: str) -> bytes:
        return self._http.request(
            "GET", f"/v1/files/{file_id}/content", expect="bytes"
        )

    def download_stream(self, file_id: str) -> Iterator[bytes]:
        return self._http.stream_bytes(f"/v1/files/{file_id}/content")


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
        """List versions of a file. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every version across pages."""

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
        """List files. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every file across pages.

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
