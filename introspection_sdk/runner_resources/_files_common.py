"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.files`."""

from __future__ import annotations

import contextlib
import json
import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from introspection_sdk.schemas.files import (
    FileType,
)

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
