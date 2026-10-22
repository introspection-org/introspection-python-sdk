"""The API references: both OpenAPI documents and the operations they hold.

introspection-cloud classifies every route in its API surface file and
writes the classification into each document as `x-introspection`: an
operation carries `{visibility: public, clients: [sdk] | [cli] | [sdk,
cli]}`, and a parameter no client is expected to send (the Data Plane's
`lane` and `project_id`) carries `clients: []`. Integration and excluded
routes are left out of the documents altogether. Those flags are the only
classification this check reads: it keeps no list of its own.
"""

from __future__ import annotations

import json
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
    "Shapes",
    "deref",
    "load_reference",
    "operations",
    "reference_source",
    "shapes",
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


def load_reference(source: str) -> dict[str, Any]:
    """An OpenAPI document from a URL or a local path."""
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


def deref(spec: dict[str, Any], schema: Any) -> dict[str, Any]:
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            break
        seen.add(ref)
        node: Any = spec
        for part in ref.removeprefix("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node
    return schema if isinstance(schema, dict) else {}


@dataclass(frozen=True)
class Shapes:
    """The reference's request body, query parameters and success response
    for one operation. `body_media` and `response` keep every media type the
    reference declares, so a call site is compared with the one it sends or
    asks for."""

    body_media: tuple[str, ...]
    body_schema: dict[str, Any] | None
    body_required: bool
    query: dict[str, Any]
    response: dict[str, Any]


def _expected(param: dict[str, Any]) -> bool:
    flags = param.get("x-introspection")
    return not (isinstance(flags, dict) and flags.get("clients") == [])


def shapes(spec: dict[str, Any], op: Operation) -> Shapes:
    raw = spec["paths"][op.path][op.method.lower()]
    content = deref(spec, raw.get("requestBody")).get("content") or {}
    params = [deref(spec, p) for p in raw.get("parameters") or []]
    # A parameter flagged `clients: []` is not one any client is expected
    # to send, so it is neither required of the SDK nor missing from it.
    query = [p for p in params if p.get("in") == "query" and _expected(p)]
    success = next(
        (r for code, r in raw.get("responses", {}).items() if code[0] == "2"),
        {},
    )
    json_body = content.get("application/json") or {}
    return Shapes(
        body_media=tuple(content),
        body_schema=json_body.get("schema"),
        body_required=bool(
            deref(spec, raw.get("requestBody")).get("required")
        ),
        query={
            "type": "object",
            "properties": {p["name"]: p.get("schema", {}) for p in query},
            "required": [p["name"] for p in query if p.get("required")],
        },
        response=deref(spec, success).get("content") or {},
    )
