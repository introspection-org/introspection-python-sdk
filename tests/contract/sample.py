"""A tiny SDK and a matching pair of references for the checker's tests.

`write_sdk` lays out a package the way introspection_sdk is laid out: the
call sites under `_async/` and a generated `_sync/` twin that must not be
read.
"""

from __future__ import annotations

import copy
import textwrap
from pathlib import Path
from typing import Any

RESOURCE = """
from __future__ import annotations

from typing import Any

WIDGETS = "/v1/widgets"


def _path(widget_id: str) -> str:
    return f"{WIDGETS}/{widget_id}"


class AsyncWidgets:
    def __init__(self, http: Any) -> None:
        self._http = http

    async def list(self) -> Any:
        return await self._http.request("GET", WIDGETS)

    async def create(self, name: str) -> Any:
        return await self._http.request("POST", WIDGETS, json={"name": name})

    async def get(self, widget_id: str) -> Any:
        return await self._http.request("GET", _path(widget_id))

    async def delete(self, widget_id: str) -> None:
        await self._http.request("DELETE", _path(widget_id), expect="empty")
"""


def line_of(snippet: str, resource: str = RESOURCE) -> int:
    """The line of the sample resource module a snippet starts on."""
    lines = textwrap.dedent(resource).splitlines()
    return next(i for i, line in enumerate(lines, 1) if snippet in line)


def write_sdk(root: Path, resource: str = RESOURCE) -> None:
    package = root / "sample_sdk"
    (package / "_async").mkdir(parents=True)
    (package / "_sync").mkdir()
    (package / "__init__.py").write_text("")
    (package / "_async" / "__init__.py").write_text("")
    (package / "_sync" / "__init__.py").write_text("")
    (package / "_async" / "widgets.py").write_text(textwrap.dedent(resource))
    # Generated code: a route here must never count as a call site.
    (package / "_sync" / "widgets.py").write_text(
        'def f(http):\n    http.request("GET", "/v1/generated-only")\n'
    )


SDK = {"visibility": "public", "clients": ["sdk"]}
CLI = {"visibility": "public", "clients": ["cli"]}

DATAPLANE: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/v1/widgets": {
            "get": {"x-introspection": SDK, "responses": {}},
            "post": {"x-introspection": SDK, "responses": {}},
        },
        "/v1/widgets/{widget_id}": {
            "parameters": [],
            "get": {"x-introspection": SDK, "responses": {}},
            "delete": {"x-introspection": SDK, "responses": {}},
        },
        "/v1/gadgets": {"get": {"x-introspection": CLI, "responses": {}}},
    },
}

CONTROLPLANE: dict[str, Any] = {"openapi": "3.1.0", "paths": {}}


def references() -> dict[str, dict[str, Any]]:
    return {
        "controlplane": copy.deepcopy(CONTROLPLANE),
        "dataplane": copy.deepcopy(DATAPLANE),
    }
