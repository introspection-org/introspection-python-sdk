"""Code shared by the sync and async twins in :mod:`introspection_sdk._http`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RawResponse:
    """A raw response body plus headers, returned by ``request(expect="raw")``.

    Used by the Arrow list-read path, where the row values arrive in the
    columnar body and pagination metadata (``X-Next-Cursor`` /
    ``X-Result-Count`` / ``X-Truncated`` / ``X-Total-Count``) moves to
    response headers. Keeps ``httpx`` off the resource layer's surface.
    """

    content: bytes
    headers: Mapping[str, str]
