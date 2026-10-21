"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.connections`."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk.schemas.connections import (
    ConnectionCreateRequest,
)

CONNECTIONS_PATH = "/v1/connections"


def _path(connection_id: UUID | str) -> str:
    return f"{CONNECTIONS_PATH}/{quote(str(connection_id), safe='')}"


def _list_params(
    *,
    member_id: UUID | str | None,
    app: str | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "member_id": str(member_id) if member_id else None,
        "app": app,
        "limit": limit,
        "next": cursor,
    }


def _create_body(app: str, runtime: str | UUID) -> dict[str, Any]:
    return ConnectionCreateRequest(app=app, runtime=str(runtime)).model_dump(
        mode="json"
    )


def _runner_runtime(
    runtime: str | UUID | None, runtime_group_id: UUID | None
) -> str | UUID:
    if runtime is not None:
        return runtime
    if runtime_group_id is None:
        raise ValueError(
            "This runner's runtime context has no runtime_group_id, so "
            "runner.connections.create() cannot say which runtime's sessions "
            "use the connection. Pass runtime= explicitly, or open the "
            "runner from a runtime with client.runtimes(...).run()."
        )
    return runtime_group_id
