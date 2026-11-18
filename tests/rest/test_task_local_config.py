"""``local_config`` on ``runner.tasks.create``: the eval task's binding files.

Each test asserts the exact JSON body the SDK sends, sync and async alike.
"""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk import IntrospectionAPIError
from introspection_sdk.runner_resources.tasks import AsyncTasks, Tasks
from introspection_sdk.schemas.tasks import (
    ApiLocalConfig,
    LocalApiBinding,
    LocalMcpServer,
    McpLocalConfig,
    TaskCreateRequest,
    TaskKind,
    TaskLocalConfig,
)

from .conftest import FakeAPI, task_create_response

COMPOSE = {
    "services": {"crm": {"image": "crm:1"}, "mail": {"image": "mail:1"}}
}

MCP = McpLocalConfig(
    servers=[
        LocalMcpServer(
            id="crm",
            name="CRM",
            transport="streamable_http",
            url="http://crm:8080/mcp",
            headers={"Authorization": "Bearer trial"},
            http_fetch="node-http1",
        )
    ]
)
MCP_WIRE = {
    "servers": [
        {
            "id": "crm",
            "name": "CRM",
            "transport": "streamable_http",
            "url": "http://crm:8080/mcp",
            "headers": {"Authorization": "Bearer trial"},
            "httpFetch": "node-http1",
        }
    ]
}
API = ApiLocalConfig(
    apis=[
        LocalApiBinding(
            host="api.mail.example",
            url="http://mail:9000",
            headers={"X-Trial": "1"},
        )
    ]
)
API_WIRE = {
    "apis": [
        {
            "host": "api.mail.example",
            "url": "http://mail:9000",
            "headers": {"X-Trial": "1"},
        }
    ]
}


def _create_sync(fake_api: FakeAPI, **kwargs: Any) -> dict[str, Any]:
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    Tasks(fake_api.client()).create(
        prompt="run the trial", kind=TaskKind.EVAL, compose=COMPOSE, **kwargs
    )
    return fake_api.last_request.json()


async def _create_async(fake_api: FakeAPI, **kwargs: Any) -> dict[str, Any]:
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    await AsyncTasks(fake_api.async_client()).create(
        prompt="run the trial", kind=TaskKind.EVAL, compose=COMPOSE, **kwargs
    )
    return fake_api.last_request.json()


CASES = [
    pytest.param(TaskLocalConfig(mcp=MCP), {"mcp": MCP_WIRE}, id="mcp-only"),
    pytest.param(TaskLocalConfig(api=API), {"api": API_WIRE}, id="api-only"),
    pytest.param(
        TaskLocalConfig(mcp=MCP, api=API),
        {"mcp": MCP_WIRE, "api": API_WIRE},
        id="both",
    ),
    pytest.param(
        TaskLocalConfig(
            mcp=McpLocalConfig(
                servers=[LocalMcpServer(id="crm", url="http://crm:8080/mcp")]
            ),
            api=ApiLocalConfig(
                apis=[
                    LocalApiBinding(host="api.mail.example", url="http://mail")
                ]
            ),
        ),
        {
            "mcp": {"servers": [{"id": "crm", "url": "http://crm:8080/mcp"}]},
            "api": {
                "apis": [{"host": "api.mail.example", "url": "http://mail"}]
            },
        },
        id="none-fields-omitted",
    ),
    pytest.param(
        {
            "mcp": {
                "servers": [
                    {
                        "id": "crm",
                        "url": "http://crm:8080/mcp",
                        "httpFetch": "default",
                        "headers": None,
                    }
                ]
            },
            "api": None,
        },
        {
            "mcp": {
                "servers": [
                    {
                        "id": "crm",
                        "url": "http://crm:8080/mcp",
                        "httpFetch": "default",
                    }
                ]
            }
        },
        id="dict-with-httpFetch-alias",
    ),
]


@pytest.mark.parametrize(("local_config", "wire"), CASES)
def test_create_sends_local_config(
    fake_api: FakeAPI, local_config: Any, wire: dict[str, Any]
):
    body = _create_sync(fake_api, local_config=local_config)
    assert body["local_config"] == wire
    assert body["kind"] == "eval"
    assert body["compose"] == COMPOSE


@pytest.mark.parametrize(("local_config", "wire"), CASES)
async def test_async_create_sends_local_config(
    fake_api: FakeAPI, local_config: Any, wire: dict[str, Any]
):
    body = await _create_async(fake_api, local_config=local_config)
    assert body["local_config"] == wire
    assert body["kind"] == "eval"


def test_create_omits_local_config_when_not_passed(fake_api: FakeAPI):
    assert "local_config" not in _create_sync(fake_api)


async def test_async_create_omits_local_config_when_not_passed(
    fake_api: FakeAPI,
):
    assert "local_config" not in await _create_async(fake_api)


def test_http_fetch_accepts_field_name_and_alias():
    by_name = LocalMcpServer(id="a", url="http://a", http_fetch="default")
    by_alias = LocalMcpServer.model_validate(
        {"id": "a", "url": "http://a", "httpFetch": "default"}
    )
    assert by_name == by_alias
    assert by_name.http_fetch == "default"


def test_start_forwards_local_config(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tasks", json_body=task_create_response())
    Tasks(fake_api.client()).start(
        prompt="go",
        kind="eval",
        compose=COMPOSE,
        local_config=TaskLocalConfig(api=API),
    )
    assert fake_api.last_request.json()["local_config"] == {"api": API_WIRE}


def test_server_refusal_surfaces_as_api_error(fake_api: FakeAPI):
    # The server, not the SDK, checks kind=eval and that each url host is a
    # compose service.
    fake_api.add(
        "POST",
        "/v1/tasks",
        status=422,
        json_body={
            "detail": "local_config is accepted on kind=eval tasks only"
        },
    )
    with pytest.raises(IntrospectionAPIError) as exc:
        Tasks(fake_api.client()).create(
            prompt="go", local_config=TaskLocalConfig(api=API)
        )
    assert exc.value.status_code == 422
    assert fake_api.last_request.json()["local_config"] == {"api": API_WIRE}


def test_local_config_tolerates_fields_the_server_adds():
    config = TaskLocalConfig.model_validate(
        {
            "mcp": {
                "servers": [
                    {"id": "crm", "url": "http://crm", "timeoutMs": 500}
                ],
                "version": 2,
            },
            "env": {"A": "1"},
        }
    )
    assert config.mcp is not None
    assert config.mcp.servers[0].model_extra == {"timeoutMs": 500}
    assert config.file_content() == {
        "mcp": {
            "servers": [{"id": "crm", "url": "http://crm", "timeoutMs": 500}],
            "version": 2,
        },
        "env": {"A": "1"},
    }


def test_create_request_mirror_carries_local_config():
    request = TaskCreateRequest.model_validate(
        {"kind": "eval", "local_config": {"api": API_WIRE}}
    )
    assert request.local_config == TaskLocalConfig(api=API)
