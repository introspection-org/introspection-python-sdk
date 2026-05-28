"""`runner.files.*` namespace: list / upload / download / versions.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from introspection_sdk._http import _HttpClient
from introspection_sdk.schemas.files import (
    File,
    FileCreateTextRequest,
    FileType,
    FileUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated

FileLike = Path | IO[bytes] | bytes


def _materialise_upload(
    file: FileLike,
    name: str | None,
    content_type: str | None,
) -> tuple[str, IO[bytes] | bytes, str]:
    if isinstance(file, Path):
        guessed_name = name or file.name
        guessed_ct = (
            content_type
            or mimetypes.guess_type(guessed_name)[0]
            or "application/octet-stream"
        )
        return guessed_name, file.open("rb"), guessed_ct
    if isinstance(file, (bytes, bytearray)):
        if not name:
            raise ValueError("`name` is required when uploading raw bytes")
        ct = content_type or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        return name, bytes(file), ct
    # file-like object
    if not name:
        raise ValueError(
            "`name` is required when uploading a file-like object"
        )
    ct = content_type or (
        mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    return name, file, ct


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
    ) -> Paginated[File]:
        params: dict[str, Any] = {
            "limit": limit,
            "next": next,
            "include_total": include_total,
        }
        payload = self._http.request(
            "GET", f"/v1/files/{file_id}/versions", params=params
        )
        return Paginated[File].model_validate(payload)

    def iter(self, file_id: str, **filters: Any) -> Iterator[File]:
        next_token: str | None = filters.pop("next", None)
        while True:
            page = self.list(file_id, next=next_token, **filters)
            yield from page.records
            if not page.next:
                return
            next_token = page.next

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
        n, body, ct = _materialise_upload(file, name, content_type)
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
    ) -> Paginated[File]:
        params: dict[str, Any] = {
            "limit": limit,
            "next": next,
            "include_total": include_total,
            "name": name,
            "file_type": (
                file_type.value
                if isinstance(file_type, FileType)
                else file_type
            ),
            "storage_path": storage_path,
        }
        payload = self._http.request("GET", "/v1/files", params=params)
        return Paginated[File].model_validate(payload)

    def iter(self, **filters: Any) -> Iterator[File]:
        next_token: str | None = filters.pop("next", None)
        while True:
            page = self.list(next=next_token, **filters)
            yield from page.records
            if not page.next:
                return
            next_token = page.next

    def upload(
        self,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
    ) -> File:
        """Upload a binary file via multipart.

        Example:
            >>> runner.files.upload(
            ...     file=Path("input.jsonl"),
            ...     file_type="upload",
            ... )
        """
        n, body, ct = _materialise_upload(file, name, content_type)
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
            "POST", "/v1/files", files=files, data=data
        )
        return File.model_validate(payload)

    def create_text(
        self,
        *,
        name: str,
        content: str,
        mime_type: str = "text/markdown",
    ) -> File:
        """Create a text/markdown file via JSON body."""
        body = FileCreateTextRequest(
            name=name, content=content, mime_type=mime_type
        )
        payload = self._http.request(
            "POST", "/v1/files", json=body.model_dump()
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
    ) -> File:
        body = FileUpdateRequest(name=name, metadata=metadata).model_dump(
            exclude_none=True
        )
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
