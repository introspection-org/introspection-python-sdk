"""The API references: both OpenAPI documents and the operations they hold.

Each plane serves its own document at `/openapi.json`, the one
introspection-cloud writes from its API surface file. An operation is for
every client unless it carries `x-introspection: {clients: [...]}`, which
names the clients expected to call it; `[]` names none. Integration and
excluded routes are left out of the documents altogether. Those flags are
the only classification this check reads: it keeps no list of its own.

The Data Plane has no fixed staging host: `STAGING_DP_URL` names the base
URL of the staging deployment whose document is read.
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
    "CLIENT",
    "CONTROLPLANE_URL",
    "DATAPLANE_BASE_VAR",
    "ENV_VARS",
    "HTTP_METHODS",
    "MissingDataplaneUrl",
    "Operation",
    "load_reference",
    "operations",
    "reference_source",
    "template_key",
]

#: The client this SDK is, as `x-introspection.clients` names it.
CLIENT = "sdk"

#: The staging Control Plane's document, which the SDK and CLI checks read.
CONTROLPLANE_URL = "https://api.staging.introspection.dev/openapi.json"

#: The variable holding the staging Data Plane's base URL; its document is
#: `/openapi.json` under it.
DATAPLANE_BASE_VAR = "STAGING_DP_URL"

#: Environment variables that replace a default URL with a URL or a file.
ENV_VARS = {
    "controlplane": "API_CONTRACT_CONTROLPLANE",
    "dataplane": "API_CONTRACT_DATAPLANE",
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


class MissingDataplaneUrl(RuntimeError):
    """No Data Plane document was named and `STAGING_DP_URL` is unset."""

    def __init__(self) -> None:
        super().__init__(
            f"{DATAPLANE_BASE_VAR} is unset or empty: set it to the staging "
            "Data Plane's base URL (the workflow reads the org-level Actions "
            f"variable vars.{DATAPLANE_BASE_VAR}), or pass --dataplane"
        )


def reference_source(plane: str, override: str | None = None) -> str:
    """The flag, else the environment variable, else the staging document."""
    source = override or os.environ.get(ENV_VARS[plane])
    if source:
        return source
    if plane == "controlplane":
        return CONTROLPLANE_URL
    base = os.environ.get(DATAPLANE_BASE_VAR, "").strip()
    if not base:
        raise MissingDataplaneUrl
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
