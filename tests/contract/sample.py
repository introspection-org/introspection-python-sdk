"""A tiny SDK and a matching pair of references for the checker's tests.

`write_sdk` lays out a package the way introspection_sdk is laid out: the
call sites under `_async/`, a generated `_sync/` twin that must not be read,
and pydantic models in their own module.
"""

from __future__ import annotations

import copy
import textwrap
from pathlib import Path
from typing import Any

MODELS = """
from __future__ import annotations

from pydantic import BaseModel


class Widget(BaseModel):
    id: str
    name: str
    size: int | None = None


class WidgetCreate(BaseModel):
    name: str
    size: int | None = None


class WidgetPage(BaseModel):
    records: list[Widget]
    next: str | None = None
"""

RESOURCE = """
from __future__ import annotations

from typing import Any

from sample_sdk.models import Widget, WidgetCreate, WidgetPage

WIDGETS = "/v1/widgets"


def _path(widget_id: str) -> str:
    return f"{WIDGETS}/{widget_id}"


def _list_params(*, name: str | None, limit: int | None) -> dict[str, Any]:
    return {"name": name, "limit": limit}


class AsyncWidgets:
    def __init__(self, http: Any) -> None:
        self._http = http

    async def list(self, *, name: str | None = None, limit: int | None = None) -> WidgetPage:
        payload = await self._http.request(
            "GET", WIDGETS, params=_list_params(name=name, limit=limit)
        )
        return WidgetPage.model_validate(payload)

    async def create(self, name: str, size: int | None = None) -> Widget:
        payload = await self._http.request(
            "POST", WIDGETS, json=WidgetCreate(name=name, size=size).model_dump()
        )
        return Widget.model_validate(payload)

    async def get(self, widget_id: str) -> Widget:
        return Widget.model_validate(
            await self._http.request("GET", _path(widget_id))
        )

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
    (package / "models.py").write_text(textwrap.dedent(MODELS))
    (package / "_async" / "widgets.py").write_text(textwrap.dedent(resource))
    # Generated code: a route here must never count as a call site.
    (package / "_sync" / "widgets.py").write_text(
        'def f(http):\n    http.request("GET", "/v1/generated-only")\n'
    )


SDK = {"visibility": "public", "clients": ["sdk"]}
CLI = {"visibility": "public", "clients": ["cli"]}

WIDGET = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "size": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
    "required": ["id", "name"],
}

DATAPLANE: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/v1/widgets": {
            "get": {
                "x-introspection": SDK,
                "parameters": [
                    {
                        "name": "name",
                        "in": "query",
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "lane",
                        "in": "query",
                        "schema": {"type": "string"},
                        "x-introspection": {
                            "clients": [],
                            "reason": "session lane",
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/WidgetPage"
                                }
                            }
                        }
                    }
                },
            },
            "post": {
                "x-introspection": SDK,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/WidgetCreate"
                            }
                        }
                    },
                },
                "responses": {
                    "201": {"$ref": "#/components/responses/Widget"}
                },
            },
        },
        "/v1/widgets/{widget_id}": {
            "parameters": [],
            "get": {
                "x-introspection": SDK,
                "responses": {
                    "200": {"$ref": "#/components/responses/Widget"}
                },
            },
            "delete": {"x-introspection": SDK, "responses": {"204": {}}},
        },
        "/v1/gadgets": {"get": {"x-introspection": CLI, "responses": {}}},
    },
    "components": {
        "responses": {
            "Widget": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Widget"}
                    }
                }
            }
        },
        "schemas": {
            "Widget": WIDGET,
            "WidgetCreate": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "size": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                },
                "required": ["name"],
            },
            "WidgetPage": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Widget"},
                    },
                    "next": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["records"],
            },
        },
    },
}

CONTROLPLANE: dict[str, Any] = {"openapi": "3.1.0", "paths": {}}


def references() -> dict[str, dict[str, Any]]:
    return {
        "controlplane": copy.deepcopy(CONTROLPLANE),
        "dataplane": copy.deepcopy(DATAPLANE),
    }
