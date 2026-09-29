"""Contract tests for connectors, connections, and the consent URL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk._errors import NotFoundError, ValidationError
from introspection_sdk.resources.connectors import (
    AsyncConnections,
    AsyncConnectors,
    Connections,
    Connectors,
)
from introspection_sdk.schemas.connectors import (
    ConnectionAuthorizationPending,
    ConnectionToken,
    ConnectorAuthorizeBinding,
    ConnectorOAuthClientRegistration,
)

from .conftest import (
    CONNECTION_ID,
    CONNECTOR_ID,
    FakeAPI,
    connection_payload,
    connector_authorization_payload,
    connector_payload,
    paginated,
    to_jsonable,
)

CONNECTOR_PATH = f"/v1/connectors/{CONNECTOR_ID}"
CONNECTIONS_PATH = f"{CONNECTOR_PATH}/connections"
CONNECTION_PATH = f"{CONNECTIONS_PATH}/{CONNECTION_ID}"
AUTHORIZE_PATH = "/v1/oauth/connections/authorize"
APPS_PATH = f"{CONNECTOR_PATH}/apps"
TOKEN_PATH = "/v1/oauth/connections/token"
CUSTOM_APPS_PATH = "/v1/connectors/custom/apps"
DISCOVER_PATH = "/v1/connectors/discover-oauth"
LINEAR_MCP = "https://mcp.linear.app/mcp"


def linear_listing() -> dict[str, object]:
    return {
        "slug": "linear",
        "name": "Linear",
        "description": "Issue tracking",
        "mcp_url": LINEAR_MCP,
        "docs_url": "https://linear.app/docs/mcp",
    }


def discovery_payload(**over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "issuer": "https://mcp.linear.app",
        "authorization_endpoint": "https://mcp.linear.app/authorize",
        "token_endpoint": "https://mcp.linear.app/token",
        "registration_endpoint": "https://mcp.linear.app/register",
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["read", "write"],
        "client_id_metadata_document_supported": False,
        "resource": LINEAR_MCP,
        "redirect_uri": "https://api.test/v1/oauth/connections/callback",
        "client_id": "dyn-client",
        "client_secret": "dyn-secret",
        "client_registration": "dynamic",
    }
    payload.update(over)
    return payload


# The wire ids are strings (paths, bodies); the methods take UUIDs.
CONNECTOR_UUID = UUID(CONNECTOR_ID)
CONNECTION_UUID = UUID(CONNECTION_ID)


# --- connectors CRUD ------------------------------------------------


def test_create_sends_only_the_fields_given(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connectors", json_body=connector_payload())
    connectors = Connectors(fake_api.client())

    created = connectors.create(
        name="Slack (support)",
        provider="slack",
        auth_mode="oauth_stored",
        scopes=["chat:write"],
        client_id="client-abc",
        client_secret="secret-xyz",
    )

    assert created.slug == "slack-support"
    # The write-only secret goes up and never comes back.
    assert not hasattr(created, "client_secret")
    assert fake_api.last_request.json() == {
        "name": "Slack (support)",
        "provider": "slack",
        "auth_mode": "oauth_stored",
        "scopes": ["chat:write"],
        "client_id": "client-abc",
        "client_secret": "secret-xyz",
    }
    assert "project" not in fake_api.last_request.params


def test_create_carries_person_server_configuration(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connectors", json_body=connector_payload())

    Connectors(fake_api.client()).create(
        name="Bookings",
        provider="booking",
        auth_mode="person_authorized",
        person_server_mode="byo",
        person_server_url="https://person.example.com",
        approval_policy="judge_advises_human",
    )

    assert fake_api.last_request.json() == {
        "name": "Bookings",
        "provider": "booking",
        "auth_mode": "person_authorized",
        "person_server_mode": "byo",
        "person_server_url": "https://person.example.com",
        "approval_policy": "judge_advises_human",
    }


def test_list_uses_authenticated_project_and_follows_the_cursor(
    fake_api: FakeAPI,
):
    pages = iter(
        [
            paginated([connector_payload()], next="cursor-2"),
            paginated([connector_payload(slug="gmail-ops")]),
        ]
    )
    fake_api.add_handler(
        "GET",
        "/v1/connectors",
        lambda _request: httpx.Response(200, json=to_jsonable(next(pages))),
    )
    connectors = Connectors(fake_api.client())

    streamed = [c.slug for c in connectors.list(limit=50)]

    assert streamed == ["slack-support", "gmail-ops"]
    first, second = fake_api.requests[0], fake_api.requests[1]
    assert "project" not in first.params
    assert first.params["limit"] == "50"
    assert "next" not in first.params
    # The cursor from page 1 must be sent on the page-2 request.
    assert second.params["next"] == "cursor-2"


def test_get_and_delete_round_trip(fake_api: FakeAPI):
    fake_api.add("GET", CONNECTOR_PATH, json_body=connector_payload())
    fake_api.add("DELETE", CONNECTOR_PATH, status=204)
    connectors = Connectors(fake_api.client())

    fetched = connectors.get(CONNECTOR_UUID)
    assert str(fetched.id) == CONNECTOR_ID
    assert fetched.requires_runtime is True

    assert connectors.delete(CONNECTOR_UUID) is None
    assert fake_api.last_request.method == "DELETE"


def test_update_sends_only_the_mutable_fields_given(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        CONNECTOR_PATH,
        json_body=connector_payload(name="Slack (renamed)"),
    )
    connectors = Connectors(fake_api.client())

    updated = connectors.update(CONNECTOR_UUID, name="Slack (renamed)")

    assert updated.name == "Slack (renamed)"
    # An omitted secret is "unchanged", so it must not ride along as null.
    assert fake_api.last_request.json() == {"name": "Slack (renamed)"}


def test_update_rotates_a_secret_without_touching_anything_else(
    fake_api: FakeAPI,
):
    fake_api.add("PATCH", CONNECTOR_PATH, json_body=connector_payload())

    Connectors(fake_api.client()).update(
        CONNECTOR_UUID, client_secret="rotated-secret"
    )

    assert fake_api.last_request.json() == {"client_secret": "rotated-secret"}


# --- authorize ------------------------------------------------------


def test_authorize_mints_a_url_with_both_expiry_forms(fake_api: FakeAPI):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )
    connectors = Connectors(fake_api.client())

    minted = connectors.authorize(
        CONNECTOR_UUID, runtime="support-agent", expires_in=3600
    )

    assert minted.authorize_url.startswith("https://slack.com/oauth")
    assert minted.expires_in == 3600
    assert isinstance(minted.expires_at, datetime)
    # `state` is the capability; it travels only inside authorize_url.
    assert not hasattr(minted, "state")
    assert fake_api.last_request.json() == {
        "connector_id": CONNECTOR_ID,
        "runtime": "support-agent",
        "expires_in": 3600,
    }


def test_authorize_sends_only_the_connector_when_told_nothing_else(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        AUTHORIZE_PATH,
        json_body=connector_authorization_payload(expires_in=600),
    )

    Connectors(fake_api.client()).authorize(CONNECTOR_UUID)

    assert fake_api.last_request.json() == {"connector_id": CONNECTOR_ID}


def test_pipedream_apps_and_progressive_scope_authorization(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        APPS_PATH,
        json_body={
            "data": [
                {
                    "slug": "google_sheets",
                    "name": "Google Sheets",
                    "icon_url": "https://assets.example/sheets.png",
                    "auth_type": "oauth",
                }
            ]
        },
    )
    connectors = Connectors(fake_api.client())

    apps = connectors.list_apps(CONNECTOR_UUID, query="sheets", limit=5)

    assert apps[0].slug == "google_sheets"
    assert dict(fake_api.last_request.params) == {
        "q": "sheets",
        "limit": "5",
    }

    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )
    connectors.authorize(
        CONNECTOR_UUID,
        runtime="coding-agent",
        app="google_sheets",
        allow_progressive_scopes=True,
    )
    assert fake_api.last_request.json() == {
        "connector_id": CONNECTOR_ID,
        "runtime": "coding-agent",
        "app": "google_sheets",
        "allow_progressive_scopes": True,
    }


def test_create_sends_pipedream_provider_workspace_id(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/connectors",
        json_body=connector_payload(
            provider="pipedream", auth_mode="client_credentials"
        ),
    )

    created = Connectors(fake_api.client()).create(
        name="Pipedream Connect",
        provider="pipedream",
        auth_mode="client_credentials",
        client_id="pd-client",
        client_secret="pd-secret",
        metadata={"provider_workspace_id": "proj_abc"},
    )

    assert created.auth_mode == "client_credentials"
    assert fake_api.last_request.json()["metadata"] == {
        "provider_workspace_id": "proj_abc"
    }


def test_search_custom_apps_reads_the_open_registry(fake_api: FakeAPI):
    fake_api.add(
        "GET", CUSTOM_APPS_PATH, json_body={"data": [linear_listing()]}
    )

    apps = Connectors(fake_api.client()).search_custom_apps("linear", limit=5)

    assert apps[0].mcp_url == LINEAR_MCP
    assert apps[0].docs_url == "https://linear.app/docs/mcp"
    # No connector id and no project: the registry precedes any connector.
    assert fake_api.last_request.path == CUSTOM_APPS_PATH
    assert dict(fake_api.last_request.params) == {"q": "linear", "limit": "5"}


def test_search_custom_apps_omits_an_unset_limit(fake_api: FakeAPI):
    fake_api.add("GET", CUSTOM_APPS_PATH, json_body={"data": []})

    assert Connectors(fake_api.client()).search_custom_apps("li") == []
    assert dict(fake_api.last_request.params) == {"q": "li"}


def test_search_custom_apps_surfaces_a_short_query_422(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        CUSTOM_APPS_PATH,
        status=422,
        json_body={"detail": "String should have at least 2 characters"},
    )

    with pytest.raises(ValidationError) as excinfo:
        Connectors(fake_api.client()).search_custom_apps("l")

    assert excinfo.value.status_code == 422


def test_discover_oauth_returns_a_registered_client(fake_api: FakeAPI):
    fake_api.add("POST", DISCOVER_PATH, json_body=discovery_payload())

    discovered = Connectors(fake_api.client()).discover_oauth(LINEAR_MCP)

    assert fake_api.last_request.json() == {"issuer": LINEAR_MCP}
    assert "project" not in fake_api.last_request.params
    assert discovered.client_registration is (
        ConnectorOAuthClientRegistration.DYNAMIC
    )
    assert discovered.client_id == "dyn-client"
    assert discovered.client_secret == "dyn-secret"
    assert discovered.scopes_supported == ["read", "write"]
    assert discovered.resource == LINEAR_MCP


def test_discover_oauth_without_automatic_registration(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        DISCOVER_PATH,
        json_body={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "redirect_uri": "https://api.test/callback",
        },
    )

    discovered = Connectors(fake_api.client()).discover_oauth(
        "https://auth.example.com"
    )

    assert discovered.client_registration is None
    assert discovered.client_id is None
    assert discovered.code_challenge_methods_supported == []
    assert discovered.client_id_metadata_document_supported is False


def test_discover_oauth_surfaces_the_discovery_400(fake_api: FakeAPI):
    detail = "No OAuth authorization server metadata found"
    fake_api.add(
        "POST", DISCOVER_PATH, status=400, json_body={"detail": detail}
    )

    with pytest.raises(ValidationError) as excinfo:
        Connectors(fake_api.client()).discover_oauth("https://nope.example")

    assert excinfo.value.status_code == 400
    assert detail in str(excinfo.value)


def test_authorize_sends_an_mcp_binding(fake_api: FakeAPI):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )

    Connectors(fake_api.client()).authorize(
        CONNECTOR_UUID,
        runtime="support-agent",
        binding={
            "environment": "production",
            "mcp_server_id": "linear",
            "url": LINEAR_MCP,
        },
    )

    # Unset optional binding fields stay off the wire.
    assert fake_api.last_request.json() == {
        "connector_id": CONNECTOR_ID,
        "runtime": "support-agent",
        "binding": {
            "environment": "production",
            "mcp_server_id": "linear",
            "url": LINEAR_MCP,
        },
    }


def test_authorize_binding_carries_name_and_headers(fake_api: FakeAPI):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )

    Connectors(fake_api.client()).authorize(
        CONNECTOR_UUID,
        runtime="support-agent",
        binding=ConnectorAuthorizeBinding(
            environment="staging",
            mcp_server_id="linear_mcp",
            url=LINEAR_MCP,
            name="Linear",
            headers={"X-Team": "eng"},
        ),
    )

    assert fake_api.last_request.json()["binding"] == {
        "environment": "staging",
        "mcp_server_id": "linear_mcp",
        "url": LINEAR_MCP,
        "name": "Linear",
        "headers": {"X-Team": "eng"},
    }


def test_authorize_rejects_an_invalid_mcp_server_id_before_sending(
    fake_api: FakeAPI,
):
    with pytest.raises(PydanticValidationError):
        Connectors(fake_api.client()).authorize(
            CONNECTOR_UUID,
            runtime="support-agent",
            binding={
                "environment": "production",
                "mcp_server_id": "Linear!",
                "url": LINEAR_MCP,
            },
        )

    assert fake_api.requests == []


def test_authorize_surfaces_the_missing_runtime_422(fake_api: FakeAPI):
    detail = (
        "`runtime` is required for a slack connector — "
        "it names the agent that replies"
    )
    fake_api.add(
        "POST", AUTHORIZE_PATH, status=422, json_body={"detail": detail}
    )
    connectors = Connectors(fake_api.client())

    with pytest.raises(ValidationError) as excinfo:
        connectors.authorize(CONNECTOR_UUID)

    assert excinfo.value.status_code == 422
    assert detail in str(excinfo.value)


def test_disabled_deployment_404_keeps_the_servers_wording(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        CONNECTOR_PATH,
        status=404,
        json_body={"detail": "Connectors are not enabled"},
    )
    connectors = Connectors(fake_api.client())

    with pytest.raises(NotFoundError) as excinfo:
        connectors.get(CONNECTOR_UUID)

    # "not enabled for this deployment", not "no such connector".
    assert "Connectors are not enabled" in str(excinfo.value)


# --- connections ----------------------------------------------------


def test_connections_list_targets_the_nested_path(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        CONNECTIONS_PATH,
        json_body=paginated([connection_payload()]),
    )
    connections = Connections(fake_api.client())

    page = connections.list(CONNECTOR_UUID, limit=25).page()

    assert page.records[0].subject_type == "workspace"
    assert page.records[0].runtime_group_id is not None
    # The installer is recorded apart from the subject: for a workspace
    # install they are never the same principal.
    assert page.records[0].created_by_member_id is not None
    assert page.records[0].created_by_member_id != page.records[0].member_id
    assert fake_api.last_request.path == CONNECTIONS_PATH
    assert fake_api.last_request.params["limit"] == "25"


def test_connection_carries_the_provider_account(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        CONNECTION_PATH,
        json_body=connection_payload(
            provider_app="google_sheets", provider_account_id="apn_123"
        ),
    )

    connection = Connections(fake_api.client()).get(
        CONNECTOR_UUID, CONNECTION_UUID
    )

    assert connection.provider_app == "google_sheets"
    assert connection.provider_account_id == "apn_123"


def test_connection_provider_fields_default_to_none(fake_api: FakeAPI):
    fake_api.add("GET", CONNECTION_PATH, json_body=connection_payload())

    connection = Connections(fake_api.client()).get(
        CONNECTOR_UUID, CONNECTION_UUID
    )

    assert connection.provider_app is None
    assert connection.provider_account_id is None


def test_connections_create_registers_an_existing_token(fake_api: FakeAPI):
    fake_api.add("POST", CONNECTIONS_PATH, json_body=connection_payload())
    connections = Connections(fake_api.client())

    created = connections.create(
        CONNECTOR_UUID,
        access_token="xoxb-token",
        subject_type="app",
        scopes_granted=["chat:write"],
    )

    assert str(created.connector_id) == CONNECTOR_ID
    # The token is accepted but never serialized back.
    assert not hasattr(created, "access_token")
    assert fake_api.last_request.json() == {
        "access_token": "xoxb-token",
        "subject_type": "app",
        "scopes_granted": ["chat:write"],
    }


def test_connections_get_and_revoke(fake_api: FakeAPI):
    fake_api.add("GET", CONNECTION_PATH, json_body=connection_payload())
    fake_api.add("DELETE", CONNECTION_PATH, status=204)
    connections = Connections(fake_api.client())

    assert str(connections.get(CONNECTOR_UUID, CONNECTION_UUID).id) == (
        CONNECTION_ID
    )
    assert connections.revoke(CONNECTOR_UUID, CONNECTION_UUID) is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.path == CONNECTION_PATH


def test_connections_get_token_returns_provider_token(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        json_body={
            "token": "provider-token",
            "token_type": "bearer",
            "expires_at": None,
            "scopes": ["calendar.read"],
        },
    )
    result = Connections(fake_api.client()).get_token(
        CONNECTOR_UUID,
        subject="user",
        action="calendar.list",
        requested_permissions={"host": "calendar.example.com"},
    )

    assert isinstance(result, ConnectionToken)
    assert result.token == "provider-token"
    assert fake_api.last_request.json() == {
        "connector_id": CONNECTOR_ID,
        "subject": "user",
        "action": "calendar.list",
        "requested_permissions": {"host": "calendar.example.com"},
    }


def test_connections_get_token_preserves_pending_mission(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        status=202,
        json_body={
            "status": "authorization_pending",
            "mission_id": "33333333-3333-3333-3333-333333333333",
            "approval_url": "https://consent.example/m/333?cap=secret",
        },
    )
    result = Connections(fake_api.client()).get_token(
        CONNECTOR_UUID,
        subject="person",
        action="booking.reserve",
    )

    assert isinstance(result, ConnectionAuthorizationPending)
    assert result.status == "authorization_pending"
    assert str(result.mission_id) == "33333333-3333-3333-3333-333333333333"


# --- async twins ----------------------------------------------------


async def test_async_create_and_authorize(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connectors", json_body=connector_payload())
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )
    connectors = AsyncConnectors(fake_api.async_client())

    created = await connectors.create(
        name="Slack (support)",
        provider="slack",
        auth_mode="oauth_stored",
    )
    assert created.provider == "slack"

    minted = await connectors.authorize(
        CONNECTOR_UUID, runtime="support-agent", expires_in=3600
    )
    assert minted.expires_in == 3600
    assert fake_api.last_request.json() == {
        "connector_id": CONNECTOR_ID,
        "runtime": "support-agent",
        "expires_in": 3600,
    }


async def test_async_list_get_update_delete(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/connectors", json_body=paginated([connector_payload()])
    )
    fake_api.add("GET", CONNECTOR_PATH, json_body=connector_payload())
    fake_api.add("PATCH", CONNECTOR_PATH, json_body=connector_payload())
    fake_api.add("DELETE", CONNECTOR_PATH, status=204)
    connectors = AsyncConnectors(fake_api.async_client())

    page = await connectors.list()
    assert page.records[0].slug == "slack-support"

    assert (await connectors.get(CONNECTOR_UUID)).requires_runtime is True
    assert (await connectors.update(CONNECTOR_UUID, name="x")).provider == (
        "slack"
    )
    assert await connectors.delete(CONNECTOR_UUID) is None


async def test_async_connections_list_and_revoke(fake_api: FakeAPI):
    fake_api.add(
        "GET", CONNECTIONS_PATH, json_body=paginated([connection_payload()])
    )
    fake_api.add("GET", CONNECTION_PATH, json_body=connection_payload())
    fake_api.add("DELETE", CONNECTION_PATH, status=204)
    connections = AsyncConnections(fake_api.async_client())

    page = await connections.list(CONNECTOR_UUID)
    assert str(page.records[0].id) == CONNECTION_ID

    assert str(
        (await connections.get(CONNECTOR_UUID, CONNECTION_UUID)).id
    ) == (CONNECTION_ID)
    assert await connections.revoke(CONNECTOR_UUID, CONNECTION_UUID) is None
    assert fake_api.last_request.path == CONNECTION_PATH


async def test_async_connections_create(fake_api: FakeAPI):
    fake_api.add("POST", CONNECTIONS_PATH, json_body=connection_payload())

    created = await AsyncConnections(fake_api.async_client()).create(
        CONNECTOR_UUID, access_token="xoxb-token"
    )

    assert str(created.connector_id) == CONNECTOR_ID
    assert fake_api.last_request.json() == {"access_token": "xoxb-token"}


async def test_async_connections_get_token(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        json_body={
            "token": "provider-token",
            "token_type": "bearer",
            "scopes": [],
        },
    )
    result = await AsyncConnections(fake_api.async_client()).get_token(
        CONNECTOR_UUID
    )

    assert isinstance(result, ConnectionToken)
    assert result.token == "provider-token"


async def test_async_authorize_surfaces_the_422(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        AUTHORIZE_PATH,
        status=422,
        json_body={"detail": "`runtime` is required for a slack connector"},
    )
    connectors = AsyncConnectors(fake_api.async_client())

    with pytest.raises(ValidationError):
        await connectors.authorize(CONNECTOR_UUID)


async def test_async_search_custom_apps_and_discover_oauth(fake_api: FakeAPI):
    fake_api.add(
        "GET", CUSTOM_APPS_PATH, json_body={"data": [linear_listing()]}
    )
    fake_api.add("POST", DISCOVER_PATH, json_body=discovery_payload())
    connectors = AsyncConnectors(fake_api.async_client())

    apps = await connectors.search_custom_apps("linear", limit=3)
    assert apps[0].slug == "linear"
    assert dict(fake_api.last_request.params) == {"q": "linear", "limit": "3"}

    discovered = await connectors.discover_oauth(LINEAR_MCP)
    assert discovered.client_id == "dyn-client"
    assert fake_api.last_request.json() == {"issuer": LINEAR_MCP}


async def test_async_discover_oauth_surfaces_the_400(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        DISCOVER_PATH,
        status=400,
        json_body={"detail": "discovery failed"},
    )

    with pytest.raises(ValidationError):
        await AsyncConnectors(fake_api.async_client()).discover_oauth(
            "https://nope.example"
        )


async def test_async_authorize_sends_an_mcp_binding(fake_api: FakeAPI):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )

    await AsyncConnectors(fake_api.async_client()).authorize(
        CONNECTOR_UUID,
        runtime="support-agent",
        binding={
            "environment": "production",
            "mcp_server_id": "linear",
            "url": LINEAR_MCP,
        },
    )

    assert fake_api.last_request.json()["binding"] == {
        "environment": "production",
        "mcp_server_id": "linear",
        "url": LINEAR_MCP,
    }
