"""The API references: both OpenAPI documents and the operations they hold.

Each plane serves its own document at `/openapi.json`, the one
introspection-cloud writes from its API surface file. An operation is for
every client unless it carries `x-introspection: {clients: [...]}`, which
names the clients expected to call it; `[]` names none. Integration and
excluded routes are left out of the documents altogether. Those flags are
the only classification this check reads: it keeps no list of its own.

No host is fixed here: `INTROSPECTION_CP_URL` and `INTROSPECTION_DP_URL`
name the base URLs of the planes whose documents are read. In CI they come
from introspection-cloud's deploy dispatch (see `api_contract.urls`).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BASE_URL_VARS",
    "CLIENT",
    "HTTP_METHODS",
    "MissingBaseUrl",
    "Operation",
    "load_reference",
    "operations",
    "reference_source",
    "template_key",
]

#: The client this SDK is, as `x-introspection.clients` names it.
CLIENT = "sdk"

#: The variables holding each plane's base URL; its document is
#: `/openapi.json` under it.
BASE_URL_VARS = {
    "controlplane": "INTROSPECTION_CP_URL",
    "dataplane": "INTROSPECTION_DP_URL",
}

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

logger = logging.getLogger(__name__)


def load_reference(source: str) -> dict[str, Any]:
    """An OpenAPI document from a URL or a local path."""
    logger.info("loading API reference", extra={"source": source})
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(
            source, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=60) as res:
            return json.load(res)
    return json.loads(Path(source).read_text())


class MissingBaseUrl(RuntimeError):
    """A plane's document was not named and its base URL variable is unset."""

    def __init__(self, plane: str) -> None:
        super().__init__(
            f"{BASE_URL_VARS[plane]} is unset or empty: set it to the "
            f"{plane}'s base URL, or pass --{plane}"
        )


def reference_source(plane: str, override: str | None = None) -> str:
    """The flag, else `/openapi.json` under the plane's base URL."""
    if override:
        return override
    base = os.environ.get(BASE_URL_VARS[plane], "").strip()
    if not base:
        raise MissingBaseUrl(plane)
    return f"{base.rstrip('/')}/openapi.json"


def template_key(path: str) -> str:
    """Path parameters compare by position, not by name."""
    out: list[str] = []
    depth = 0
    for char in path:
        if char == "{":
            if depth == 0:
                out.append("{}")
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            out.append(char)
    return "".join(out)


@dataclass(frozen=True)
class Operation:
    plane: str
    method: str
    path: str
    #: The clients `x-introspection` names, or None when it names none and
    #: the operation is for every client.
    clients: tuple[str, ...] | None

    def wanted_by(self, client: str) -> bool:
        return self.clients is None or client in self.clients

    @property
    def name(self) -> str:
        return f"{self.plane}: {self.method} {self.path}"

    @property
    def key(self) -> str:
        return f"{self.method} {template_key(self.path)}"


def operations(plane: str, spec: dict[str, Any]) -> list[Operation]:
    out = []
    for path, item in spec.get("paths", {}).items():
        for method in HTTP_METHODS:
            op = item.get(method)
            if op is None:
                continue
            flags = op.get("x-introspection")
            clients = None if flags is None else flags.get("clients")
            out.append(
                Operation(
                    plane=plane,
                    method=method.upper(),
                    path=path,
                    clients=None if clients is None else tuple(clients),
                )
            )
    return out
