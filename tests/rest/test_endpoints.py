"""Contract tests for ``client.endpoints`` (CP ``/v1/endpoints``)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from introspection_sdk._errors import NotFoundError, ValidationError
from introspection_sdk.resources import AsyncEndpoints, Endpoints
from introspection_sdk.schemas.endpoints import EndpointKind, EndpointMetadata

from .conftest import (
    CONNECTOR_ID,
    MEMBER_ID,
    ORG_ID,
    PROJECT_ID,
    RUNTIME_GROUP_ID,
    FakeAPI,
)

ENDPOINT_ID = "0199a1b2-0000-7000-8000-0000000000e1"
PATH = f"/v1/endpoints/{ENDPOINT_ID}"


def endpoint(**over: Any) -> dict[str, Any]:
    return {
        "id": ENDPOINT_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "hello-mcp",
        "host": "example-server.modelcontextprotocol.io",
        "base_url": "https://example-server.modelcontextprotocol.io/mcp",
        "kind": "mcp",
        "metadata": {
            "mcp_server_id": "hello-mcp",
            "connector_id": CONNECTOR_ID,
            "provider_app": None,
            "extra_hosts": [],
            "auth_audience": None,
        },
        "assertion_claims": None,
        "runtime_id": None,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "environment": "production",
        "verify_path": None,
        "headers": {},
        "header_names": [],
        "credential_refs": [],
        "last_verified_at": None,
        "authorized_application_id": None,
        "created_by_member_id": MEMBER_ID,
        "created_at": "2026-10-21T12:00:00Z",
        "updated_at": "2026-10-21T12:00:00Z",
        **over,
    }


def page(*records: dict[str, Any]) -> dict[str, Any]:
    return {"records": list(records), "count": len(records), "next": None}


def test_list_filters_an_mcp_binding(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/endpoints", json_body=page(endpoint()))
    found = (
        Endpoints(fake_api.client())
        .list(
            project=UUID(PROJECT_ID),
            kind=EndpointKind.MCP,
            mcp_server_id="hello-mcp",
        )
        .page()
    )
    assert found.records[0].kind == EndpointKind.MCP
    assert str(found.records[0].metadata.connector_id) == CONNECTOR_ID
    params = fake_api.last_request.params
    assert params.get("project") == PROJECT_ID
    assert params.get("kind") == "mcp"
    assert params.get("mcp_server_id") == "hello-mcp"
    assert "runtime" not in params


def test_a_kind_the_api_adds_still_reads(fake_api: FakeAPI):
    fake_api.add("GET", PATH, json_body=endpoint(kind="queue"))
    assert Endpoints(fake_api.client()).get(ENDPOINT_ID).kind == "queue"


def test_update_and_delete(fake_api: FakeAPI):
    fake_api.add("PATCH", PATH, json_body=endpoint(name="renamed"))
    fake_api.add("DELETE", PATH, status=204)
    endpoints = Endpoints(fake_api.client())
    renamed = endpoints.update(
        ENDPOINT_ID,
        project=PROJECT_ID,
        name="renamed",
        metadata=EndpointMetadata(mcp_server_id="hello-mcp"),
    )
    assert renamed.name == "renamed"
    assert fake_api.last_request.json() == {
        "name": "renamed",
        "metadata": {"mcp_server_id": "hello-mcp", "extra_hosts": []},
    }
    endpoints.delete(ENDPOINT_ID, project=PROJECT_ID)
    assert fake_api.last_request.params.get("project") == PROJECT_ID


def test_a_missing_endpoint(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        Endpoints(fake_api.client()).get(ENDPOINT_ID)


async def test_async_endpoints(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/endpoints", json_body=page(endpoint()))
    fake_api.add("GET", PATH, json_body=endpoint())
    fake_api.add("PATCH", PATH, json_body=endpoint(verify_path="/health"))
    fake_api.add("DELETE", PATH, status=204)
    endpoints = AsyncEndpoints(fake_api.async_client())
    listed = [e async for e in endpoints.list(runtime="hello-mcp")]
    assert len(listed) == 1
    assert fake_api.last_request.params.get("runtime") == "hello-mcp"
    assert (await endpoints.get(ENDPOINT_ID)).name == "hello-mcp"
    updated = await endpoints.update(ENDPOINT_ID, verify_path="/health")
    assert updated.verify_path == "/health"
    assert fake_api.last_request.json() == {"verify_path": "/health"}
    await endpoints.delete(ENDPOINT_ID)
    assert fake_api.last_request.method == "DELETE"


def test_create_an_api_endpoint(fake_api: FakeAPI):
    created = endpoint(
        name="walk-api",
        host="walk.example.com",
        base_url=None,
        kind="api",
        metadata={"extra_hosts": []},
        runtime_group_id=None,
        environment=None,
        headers={"X-Walk": "${WALK_SECRET}"},
        header_names=["X-Walk"],
        credential_refs=["WALK_SECRET"],
        # A field the API adds later reads through.
        mcp_check=None,
    )
    fake_api.add("POST", "/v1/endpoints", status=201, json_body=created)
    made = Endpoints(fake_api.client()).create(
        project=PROJECT_ID,
        name="walk-api",
        host="walk.example.com",
        kind=EndpointKind.API,
        headers={"X-Walk": "${WALK_SECRET}"},
    )
    assert (made.kind, made.credential_refs) == ("api", ["WALK_SECRET"])
    assert made.model_dump(mode="json")["mcp_check"] is None
    request = fake_api.last_request
    assert (request.method, request.path) == ("POST", "/v1/endpoints")
    assert request.params.get("project") == PROJECT_ID
    assert request.json() == {
        "name": "walk-api",
        "host": "walk.example.com",
        "kind": "api",
        "headers": {"X-Walk": "${WALK_SECRET}"},
    }


def test_create_sends_empty_headers_and_reports_a_failed_verify(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        "/v1/endpoints",
        status=422,
        json_body={"detail": {"code": "endpoint_verify_failed"}},
    )
    with pytest.raises(ValidationError):
        Endpoints(fake_api.client()).create(
            name="llm", host="llm.example.com", verify_path="/v1/models"
        )
    assert fake_api.last_request.json() == {
        "name": "llm",
        "host": "llm.example.com",
        "headers": {},
        "verify_path": "/v1/models",
    }


async def test_async_create(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/endpoints", json_body=endpoint())
    made = await AsyncEndpoints(fake_api.async_client()).create(
        name="hello-mcp",
        host="example-server.modelcontextprotocol.io",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
    )
    assert made.kind == EndpointKind.MCP
    assert fake_api.last_request.json()["runtime_group_id"] == RUNTIME_GROUP_ID
