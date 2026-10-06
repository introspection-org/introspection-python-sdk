"""Contract tests for ``client.connections`` / ``runner.connections``
(DP ``/v1/connections``).

The namespace tests drive the offline :class:`FakeAPI` transport; the Runner
tests use a real loopback DP origin (``conftest.LocalDP``) so the token and
runtime group asserted are the ones the Runner took from its own spec.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest

from introspection_sdk import AsyncIntrospectionClient, IntrospectionClient
from introspection_sdk._errors import IntrospectionAPIError, NotFoundError
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.runner_resources import (
    AppConnections,
    AsyncAppConnections,
    AsyncRunnerAppConnections,
    RunnerAppConnections,
)
from introspection_sdk.schemas.connections import Connection, ConnectPage
from introspection_sdk.schemas.runner import (
    RunnerContext,
    RunnerDeployment,
    RunnerSpec,
)

from .conftest import (
    MEMBER_ID,
    RUNTIME_GROUP_ID,
    FakeAPI,
    LocalDP,
    runner_spec_payload,
)

SPEC_RUNTIME_GROUP_ID = "88888888-8888-8888-8888-888888888888"
CONNECTION_ID = "0199a1b2-0000-7000-8000-0000000000c1"
CONNECTION_PATH = f"/v1/connections/{CONNECTION_ID}"
PAGE = {
    "authorize_url": "https://connect.example/c/abc",
    "expires_in": 600,
    "expires_at": "2026-10-06T12:10:00Z",
}


def connection_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": CONNECTION_ID,
        "member_id": MEMBER_ID,
        "app": "gmail",
        "account_name": "ada@example.com",
        "healthy": True,
        "created_at": "2026-10-01T09:00:00Z",
    }
    body.update(over)
    return body


def page_of(records: list[dict[str, Any]], next: str | None = None) -> dict:
    return {"records": records, "count": len(records), "next": next}


def test_get_decodes_the_connection(fake_api: FakeAPI):
    fake_api.add("GET", CONNECTION_PATH, json_body=connection_body())

    connection = AppConnections(fake_api.client()).get(UUID(CONNECTION_ID))

    assert fake_api.last_request.method == "GET"
    assert isinstance(connection, Connection)
    assert connection.id == UUID(CONNECTION_ID)
    assert connection.member_id == UUID(MEMBER_ID)
    assert connection.app == "gmail"
    assert connection.account_name == "ada@example.com"
    assert connection.healthy is True
    assert connection.created_at == datetime(2026, 10, 1, 9, tzinfo=UTC)


def test_list_sends_filters_and_follows_the_cursor(fake_api: FakeAPI):
    pages = [
        page_of([connection_body()], next="cur-2"),
        page_of(
            [connection_body(app="slack", account_name=None, healthy=False)]
        ),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages.pop(0))

    fake_api.add_handler("GET", "/v1/connections", handler)

    connections = list(
        AppConnections(fake_api.client()).list(
            member_id=UUID(MEMBER_ID), app="gmail", limit=10
        )
    )

    assert [(c.app, c.healthy, c.account_name) for c in connections] == [
        ("gmail", True, "ada@example.com"),
        ("slack", False, None),
    ]
    assert [dict(r.params) for r in fake_api.requests] == [
        {"member_id": MEMBER_ID, "app": "gmail", "limit": "10"},
        {
            "member_id": MEMBER_ID,
            "app": "gmail",
            "limit": "10",
            "next": "cur-2",
        },
    ]


def test_list_without_filters_sends_none(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/connections", json_body=page_of([]))

    assert AppConnections(fake_api.client()).list().page().count == 0
    assert dict(fake_api.last_request.params) == {}


def test_create_sends_app_and_runtime(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connections", status=201, json_body=PAGE)

    page = AppConnections(fake_api.client()).create(
        app="gmail", runtime="support-agent"
    )

    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.json() == {
        "app": "gmail",
        "runtime": "support-agent",
    }
    assert isinstance(page, ConnectPage)
    assert page.authorize_url == "https://connect.example/c/abc"
    assert page.expires_in == 600
    assert page.expires_at == datetime(2026, 10, 6, 12, 10, tzinfo=UTC)


def test_create_accepts_a_runtime_group_id(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/connections",
        json_body={
            "authorize_url": "https://connect.example/c/x",
            "expires_in": 60,
        },
    )

    page = AppConnections(fake_api.client()).create(
        app="gmail", runtime=UUID(RUNTIME_GROUP_ID)
    )

    assert fake_api.last_request.json()["runtime"] == RUNTIME_GROUP_ID
    assert page.expires_at is None


def test_runner_create_defaults_to_its_runtime_group(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connections", json_body=PAGE)
    api = RunnerAppConnections(fake_api.client(), UUID(RUNTIME_GROUP_ID))

    api.create(app="gmail")
    assert fake_api.last_request.json() == {
        "app": "gmail",
        "runtime": RUNTIME_GROUP_ID,
    }

    api.create(app="gmail", runtime="other-runtime")
    assert fake_api.last_request.json()["runtime"] == "other-runtime"


def test_runner_create_without_a_runtime_group_raises_before_sending(
    fake_api: FakeAPI,
):
    with pytest.raises(ValueError, match="runtime_group_id"):
        RunnerAppConnections(fake_api.client(), None).create(app="gmail")
    assert fake_api.requests == []


def test_delete_escapes_the_id_and_returns_none(fake_api: FakeAPI):
    fake_api.add("DELETE", "/v1/connections/a/b", status=204)

    assert AppConnections(fake_api.client()).delete("a/b") is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.url.raw_path == b"/v1/connections/a%2Fb"


def test_get_of_another_members_connection_is_not_found(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        CONNECTION_PATH,
        status=404,
        json_body={"detail": "Connection not found"},
    )

    with pytest.raises(NotFoundError):
        AppConnections(fake_api.client()).get(CONNECTION_ID)


def test_a_token_without_the_scope_gets_403(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/connections",
        status=403,
        json_body={"detail": "Missing scope connections:read"},
    )

    with pytest.raises(IntrospectionAPIError) as exc:
        AppConnections(fake_api.client()).list().page()
    assert exc.value.status_code == 403


async def test_async_crud(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/connections",
        json_body=page_of([connection_body(), connection_body(app="slack")]),
    )
    fake_api.add("POST", "/v1/connections", status=201, json_body=PAGE)
    fake_api.add("GET", CONNECTION_PATH, json_body=connection_body())
    fake_api.add("DELETE", CONNECTION_PATH, status=204)
    api = AsyncAppConnections(fake_api.async_client())

    apps = [c.app async for c in api.list(app="gmail")]
    assert apps == ["gmail", "slack"]
    assert dict(fake_api.last_request.params) == {"app": "gmail"}

    page = await api.create(app="gmail", runtime=UUID(RUNTIME_GROUP_ID))
    assert page.expires_in == 600
    assert fake_api.last_request.json() == {
        "app": "gmail",
        "runtime": RUNTIME_GROUP_ID,
    }
    assert (await api.get(CONNECTION_ID)).app == "gmail"
    assert await api.delete(UUID(CONNECTION_ID)) is None
    assert [(r.method, r.url.path) for r in fake_api.requests] == [
        ("GET", "/v1/connections"),
        ("POST", "/v1/connections"),
        ("GET", CONNECTION_PATH),
        ("DELETE", CONNECTION_PATH),
    ]


async def test_async_runner_create_defaults_and_raises(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connections", json_body=PAGE)

    await AsyncRunnerAppConnections(
        fake_api.async_client(), UUID(RUNTIME_GROUP_ID)
    ).create(app="gmail")
    assert fake_api.last_request.json()["runtime"] == RUNTIME_GROUP_ID

    with pytest.raises(ValueError, match="runtime_group_id"):
        await AsyncRunnerAppConnections(fake_api.async_client(), None).create(
            app="gmail"
        )
    assert len(fake_api.requests) == 1


# --- Through the client and the Runner --------------------------------


def _seed(dp: LocalDP) -> None:
    dp.add("GET", "/v1/connections", page_of([connection_body()]))
    dp.add("POST", "/v1/connections", PAGE)
    dp.add("GET", CONNECTION_PATH, connection_body())
    # LocalDP always writes a JSON body, so the delete answers 200 here; the
    # 204 path is covered on the namespace above.
    dp.add("DELETE", CONNECTION_PATH, None)


def _spec(dp: LocalDP, token: str, runtime_group_id: str | None) -> RunnerSpec:
    return runner_spec_payload(
        session_token=token,
        deployment=RunnerDeployment(
            endpoint=dp.endpoint, slug="dp", region="us-east"
        ),
        runtime_context=RunnerContext(
            runtime_group_id=UUID(runtime_group_id)
            if runtime_group_id
            else None
        ),
    )


def test_client_connections_use_the_client_token(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    client = IntrospectionClient(
        token="member-jwt", base_api_url="https://api.test", dp_url=dp.endpoint
    )
    try:
        assert isinstance(client.connections, AppConnections)
        assert client.connections.list().page().count == 1
        client.connections.create(app="gmail", runtime="support-agent")
        assert client.connections.get(CONNECTION_ID).app == "gmail"
        assert client.connections.delete(CONNECTION_ID) is None
    finally:
        client.shutdown()

    assert [(r.method, r.path, r.authorization) for r in dp.requests] == [
        ("GET", "/v1/connections", "Bearer member-jwt"),
        ("POST", "/v1/connections", "Bearer member-jwt"),
        ("GET", CONNECTION_PATH, "Bearer member-jwt"),
        ("DELETE", CONNECTION_PATH, "Bearer member-jwt"),
    ]
    assert json.loads(dp.requests[1].body) == {
        "app": "gmail",
        "runtime": "support-agent",
    }


def test_runner_connections_use_the_runner_token_and_group(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    spec = _spec(dp, "runner-jwt", SPEC_RUNTIME_GROUP_ID)

    with Runner(spec, refresher=lambda: spec) as runner:
        assert isinstance(runner.connections, RunnerAppConnections)
        assert runner.connections.list().page().count == 1
        assert runner.connections.create(app="gmail").expires_in == 600
        assert runner.connections.get(CONNECTION_ID).healthy is True
        assert runner.connections.delete(CONNECTION_ID) is None

    assert [(r.method, r.path, r.authorization) for r in dp.requests] == [
        ("GET", "/v1/connections", "Bearer runner-jwt"),
        ("POST", "/v1/connections", "Bearer runner-jwt"),
        ("GET", CONNECTION_PATH, "Bearer runner-jwt"),
        ("DELETE", CONNECTION_PATH, "Bearer runner-jwt"),
    ]
    assert json.loads(dp.requests[1].body) == {
        "app": "gmail",
        "runtime": SPEC_RUNTIME_GROUP_ID,
    }


def test_runner_refresh_rebinds_the_runtime_group(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    first = _spec(dp, "jwt-a", SPEC_RUNTIME_GROUP_ID)
    second = _spec(dp, "jwt-b", RUNTIME_GROUP_ID)
    runner = Runner(first, refresher=lambda: second)
    try:
        runner.refresh()
        runner.connections.create(app="gmail")
    finally:
        runner.close()

    assert dp.requests[-1].authorization == "Bearer jwt-b"
    assert json.loads(dp.requests[-1].body)["runtime"] == RUNTIME_GROUP_ID


def test_runner_without_a_runtime_group_cannot_create(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    spec = _spec(dp, "runner-jwt", None)

    with Runner(spec, refresher=lambda: spec) as runner:
        assert runner.connections.list().page().count == 1
        with pytest.raises(ValueError, match="runtime_group_id"):
            runner.connections.create(app="gmail")

    assert [r.method for r in dp.requests] == ["GET"]


async def test_async_client_and_runner_connections(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    first = _spec(dp, "runner-jwt", SPEC_RUNTIME_GROUP_ID)
    second = _spec(dp, "runner-jwt-2", RUNTIME_GROUP_ID)

    async def refresher() -> RunnerSpec:
        return second

    async with AsyncIntrospectionClient(
        token="member-jwt", base_api_url="https://api.test", dp_url=dp.endpoint
    ) as client:
        assert isinstance(client.connections, AsyncAppConnections)
        assert (await client.connections.list().page()).count == 1
        await client.connections.create(app="gmail", runtime="support-agent")

    async with AsyncRunner(first, refresher=refresher) as runner:
        assert isinstance(runner.connections, AsyncRunnerAppConnections)
        assert (await runner.connections.create(app="gmail")).expires_in == 600
        assert (await runner.connections.get(CONNECTION_ID)).app == "gmail"
        assert await runner.connections.delete(CONNECTION_ID) is None
        await runner.refresh()
        await runner.connections.create(app="gmail")

    assert [(r.method, r.authorization) for r in dp.requests] == [
        ("GET", "Bearer member-jwt"),
        ("POST", "Bearer member-jwt"),
        ("POST", "Bearer runner-jwt"),
        ("GET", "Bearer runner-jwt"),
        ("DELETE", "Bearer runner-jwt"),
        ("POST", "Bearer runner-jwt-2"),
    ]
    assert json.loads(dp.requests[2].body)["runtime"] == SPEC_RUNTIME_GROUP_ID
    assert json.loads(dp.requests[-1].body)["runtime"] == RUNTIME_GROUP_ID
