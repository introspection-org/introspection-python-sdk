"""An eval task's local binding files, sent as ``local_config`` on task create.

The shapes are the Recipe binding files ``.pi/mcp.local.json``
(:class:`McpLocalConfig`) and ``.pi/api.local.json`` (:class:`ApiLocalConfig`),
so their keys follow that file format (``httpFetch``) rather than the API's
snake_case. :meth:`TaskLocalConfig.file_content` is the JSON the server
writes as those files: aliased keys, and no key for a field left ``None``,
since the files refuse a null value (a null ``headers``, say).

The server validates the rest: ``local_config`` needs ``kind="eval"``, every
``url`` must be a literal absolute http(s) URL whose host is a service of the
task's ``compose``, headers must be literal (no ``${VAR}``), and an MCP server
id or API host is bound at most once.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ApiLocalConfig",
    "LocalApiBinding",
    "LocalMcpServer",
    "McpLocalConfig",
    "TaskLocalConfig",
]


class LocalConfigModel(BaseModel):
    # Fields the server adds are kept, and `http_fetch=` works beside the
    # `httpFetch` wire key.
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class LocalMcpServer(LocalConfigModel):
    """One ``.pi/mcp.local.json`` server entry."""

    id: str = Field(description="Declared MCP server id this entry binds.")
    name: str | None = None
    transport: Literal["streamable_http"] | None = None
    url: str = Field(
        description="Where the server is reached: a service of the task's compose."
    )
    headers: dict[str, str] | None = Field(
        default=None, description="Literal header values sent to the server."
    )
    http_fetch: Literal["default", "node-http1"] | None = Field(
        default=None, alias="httpFetch"
    )


class McpLocalConfig(LocalConfigModel):
    """The ``.pi/mcp.local.json`` document."""

    servers: list[LocalMcpServer]


class LocalApiBinding(LocalConfigModel):
    """One ``.pi/api.local.json`` entry: requests to ``host`` go to ``url``."""

    host: str = Field(description="Bare hostname the Recipe calls.")
    url: str = Field(
        description="Where requests go instead: a service of the task's compose."
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Literal header values added to each request.",
    )


class ApiLocalConfig(LocalConfigModel):
    """The ``.pi/api.local.json`` document."""

    apis: list[LocalApiBinding]


class TaskLocalConfig(LocalConfigModel):
    """The binding files an eval task's session reads in place of the
    Recipe's committed ones."""

    mcp: McpLocalConfig | None = Field(
        default=None, description="Exact `.pi/mcp.local.json` content."
    )
    api: ApiLocalConfig | None = Field(
        default=None, description="Exact `.pi/api.local.json` content."
    )

    def file_content(self) -> dict[str, Any]:
        """The JSON sent on the wire: aliased keys, ``None`` fields omitted."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
