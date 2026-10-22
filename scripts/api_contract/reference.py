"""The API references: both OpenAPI documents and the operations they hold.

introspection-cloud classifies every route in its API surface file and
writes the classification into each document as `x-introspection`: an
operation carries `{visibility: public, clients: [sdk] | [cli] | [sdk,
cli]}`. Integration and excluded routes are left out of the documents
altogether. Those flags are the only
classification this check reads: it keeps no list of its own.
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
    "DEFAULT_URLS",
    "ENV_VARS",
    "HTTP_METHODS",
    "Operation",
    "load_reference",
    "operations",
    "reference_source",
    "template_key",
]

#: The client this SDK is, as `x-introspection.clients` names it.
CLIENT = "sdk"

#: Staging serves what the SDK and CLI checks read; production serves docs.
DEFAULT_URLS = {
    "controlplane": "https://api.staging.introspection.dev/openapi/controlplane.json",
    "dataplane": "https://api.staging.introspection.dev/openapi/dataplane.json",
}

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


def reference_source(plane: str, override: str | None = None) -> str:
    """The flag, else the environment variable, else the staging URL."""
    return override or os.environ.get(ENV_VARS[plane]) or DEFAULT_URLS[plane]


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
    clients: tuple[str, ...]

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
            flags = op.get("x-introspection") or {}
            out.append(
                Operation(
                    plane=plane,
                    method=method.upper(),
                    path=path,
                    clients=tuple(flags.get("clients") or ()),
                )
            )
    return out
