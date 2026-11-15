"""Contract tests for connectors, the token broker, and the consent URL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk._errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from introspection_sdk.resources.connectors import (
    AsyncConnectors,
    Connectors,
)
from introspection_sdk.schemas.connectors import (
    ConnectionAuthorizationPending,
    ConnectionToken,
    Connector,
    ConnectorAuthMode,
    ConnectorAuthorizeBinding,
    ConnectorCreateRequest,
    ConnectorOAuthClientRegistration,
    ConnectorUpdateRequest,
    EntityUid,
    PolicyEntity,
    WebhookSecret,
    WebhookSecretCreated,
    WebhookSecretStatus,
    WebhookSecretType,
)

from .conftest import (
    CONNECTOR_ID,
    FakeAPI,
    connector_authorization_payload,
    connector_payload,
    paginated,
    to_jsonable,
)

CONNECTOR_PATH = f"/v1/connectors/{CONNECTOR_ID}"
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
        "revocation_endpoint": "https://mcp.linear.app/revoke",
    }
    payload.update(over)
    return payload


# The wire ids are strings (paths, bodies); the methods take UUIDs.
CONNECTOR_UUID = UUID(CONNECTOR_ID)


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


APPLICATION_ID = "44444444-4444-4444-4444-444444444444"
ACME_ENTITY = {
    "uid": {"type": "Company", "id": "acme"},
    "attrs": {"business_min_level": 5},
    "parents": [{"type": "Region", "id": "emea"}],
}


def test_create_aauth_connector_sends_typed_policy_entities(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        "/v1/connectors",
        json_body=connector_payload(
            provider="booking",
            auth_mode="aauth",
            person_server_url="https://person.example.com",
            application_id=APPLICATION_ID,
            policy_entities=[ACME_ENTITY],
        ),
    )

    created = Connectors(fake_api.client()).create(
        name="Bookings",
        provider="booking",
        auth_mode=ConnectorAuthMode.AAUTH,
        person_server_url="https://person.example.com",
        application_id=UUID(APPLICATION_ID),
        policy_entities=[
            PolicyEntity(
                uid=EntityUid(type="Company", id="acme"),
                attrs={"business_min_level": 5},
                parents=[EntityUid(type="Region", id="emea")],
            )
        ],
    )

    assert fake_api.last_request.json() == {
        "name": "Bookings",
        "provider": "booking",
        "auth_mode": "aauth",
        "person_server_url": "https://person.example.com",
        "application_id": APPLICATION_ID,
        "policy_entities": [ACME_ENTITY],
    }
    assert created.auth_mode is ConnectorAuthMode.AAUTH
    assert created.policy_entities == [
        PolicyEntity.model_validate(ACME_ENTITY)
    ]


def test_create_accepts_policy_entities_as_plain_dicts(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connectors", json_body=connector_payload())

    Connectors(fake_api.client()).create(
        name="Bookings",
        provider="booking",
        auth_mode="aauth",
        person_server_url="https://person.example.com",
        application_id=UUID(APPLICATION_ID),
        policy_entities=[{"uid": {"type": "Company", "id": "acme"}}],
    )

    # attrs / parents default to empty, as Cedar's JSON entity format allows.
    assert fake_api.last_request.json()["policy_entities"] == [
        {"uid": {"type": "Company", "id": "acme"}, "attrs": {}, "parents": []}
    ]


def test_create_aauth_without_person_server_surfaces_the_422(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        "/v1/connectors",
        status=422,
        json_body={"detail": "aauth requires person_server_url"},
    )

    with pytest.raises(ValidationError):
        Connectors(fake_api.client()).create(
            name="Bookings", provider="booking", auth_mode="aauth"
        )


def test_read_parses_policy_entities(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        CONNECTOR_PATH,
        json_body=connector_payload(
            auth_mode="aauth", policy_entities=[ACME_ENTITY]
        ),
    )

    fetched = Connectors(fake_api.client()).get(CONNECTOR_UUID)

    assert fetched.policy_entities is not None
    (entity,) = fetched.policy_entities
    assert entity.uid == EntityUid(type="Company", id="acme")
    assert entity.attrs == {"business_min_level": 5}
    assert entity.parents == [EntityUid(type="Region", id="emea")]


def test_read_without_policy_entities_is_none(fake_api: FakeAPI):
    fake_api.add("GET", CONNECTOR_PATH, json_body=connector_payload())

    assert (
        Connectors(fake_api.client()).get(CONNECTOR_UUID).policy_entities
        is None
    )


def test_update_replaces_policy_entities(fake_api: FakeAPI):
    fake_api.add("PATCH", CONNECTOR_PATH, json_body=connector_payload())

    Connectors(fake_api.client()).update(
        CONNECTOR_UUID, policy_entities=[ACME_ENTITY]
    )

    assert fake_api.last_request.json() == {"policy_entities": [ACME_ENTITY]}


@pytest.mark.parametrize("field", ["approval_policy", "person_server_mode"])
def test_retired_person_server_fields_are_gone(field: str):
    # The control plane removed both; AAuth policy replaces them.
    assert field not in Connector.model_fields
    assert field not in ConnectorCreateRequest.model_fields
    assert field not in ConnectorUpdateRequest.model_fields


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


# --- webhook connectors -------------------------------------------

SECRETS_PATH = f"{CONNECTOR_PATH}/secrets"


def secret(kid: str, status: str, **over: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "id": kid,
        "type": "standard_webhooks",
        "status": status,
        "created_at": "2026-11-13T10:00:00Z",
    }
    fields.update(over)
    return fields


def secret_page(*records: dict[str, object], next: str | None = None):
    return {"records": list(records), "count": len(records), "next": next}


def webhook_payload(**over: object) -> Connector:
    fields: dict[str, object] = {
        "slug": "orders",
        "name": "Orders",
        "provider": "webhook",
        "auth_mode": "static",
        "scopes": [],
        "api_hosts": [],
        "requires_runtime": False,
    }
    fields.update(over)
    return connector_payload(**fields)


def test_create_webhook_connector_issues_no_secret(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/connectors", status=201, json_body=webhook_payload()
    )

    created = Connectors(fake_api.client()).create(
        name="Orders", provider="webhook", auth_mode="static", slug="orders"
    )

    assert fake_api.last_request.json() == {
        "name": "Orders",
        "provider": "webhook",
        "auth_mode": "static",
        "slug": "orders",
    }
    assert type(created) is Connector
    assert "signing_secrets" not in Connector.model_fields
    assert "signing_secret" not in Connector.model_fields


def test_list_webhook_secrets_pages_through_the_cursor(fake_api: FakeAPI):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("next") == "c2":
            body = secret_page(secret("1a2b3c4d", "previous"))
        else:
            body = secret_page(
                secret(
                    "5e6f7a8b", "current", created_at="2026-11-14T10:00:00Z"
                ),
                next="c2",
            )
        return httpx.Response(200, json=body)

    fake_api.add_handler("GET", SECRETS_PATH, handler)

    listed = list(
        Connectors(fake_api.client()).secrets.list(CONNECTOR_UUID, limit=1)
    )

    current, previous = listed
    assert all(type(s) is WebhookSecret for s in listed)
    assert current.status is WebhookSecretStatus.CURRENT
    assert current.created_at == datetime.fromisoformat(
        "2026-11-14T10:00:00+00:00"
    )
    assert previous.id == "1a2b3c4d"
    assert previous.type is WebhookSecretType.STANDARD_WEBHOOKS
    assert previous.status is WebhookSecretStatus.PREVIOUS
    assert [dict(r.params) for r in fake_api.requests] == [
        {"limit": "1"},
        {"limit": "1", "next": "c2"},
    ]


def test_list_webhook_secrets_starts_at_a_given_cursor(fake_api: FakeAPI):
    fake_api.add("GET", SECRETS_PATH, json_body=secret_page())

    page = Connectors(fake_api.client()).secrets.list(
        CONNECTOR_UUID, next="c2"
    )

    assert list(page) == []
    assert dict(fake_api.last_request.params) == {"next": "c2"}


def test_a_listed_secret_tolerates_a_new_type_and_status(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        SECRETS_PATH,
        json_body=secret_page(secret("1a2b3c4d", "retiring", type="mtls")),
    )

    (listed,) = Connectors(fake_api.client()).secrets.list(CONNECTOR_UUID)

    assert listed.type == "mtls"
    assert listed.status == "retiring"


@pytest.mark.parametrize(
    ("secret_type", "issued"),
    [
        (WebhookSecretType.STANDARD_WEBHOOKS, "whsec_first"),
        ("bearer", "whtok_first"),
    ],
)
def test_create_the_first_webhook_secret_names_its_type(
    fake_api: FakeAPI, secret_type: WebhookSecretType | str, issued: str
):
    fake_api.add(
        "POST",
        SECRETS_PATH,
        status=201,
        json_body=secret(
            "1a2b3c4d", "current", type=str(secret_type), secret=issued
        ),
    )

    created = Connectors(fake_api.client()).secrets.create(
        CONNECTOR_UUID, type=secret_type
    )

    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.json() == {"type": str(secret_type)}
    assert type(created) is WebhookSecretCreated
    assert created.secret.get_secret_value() == issued
    assert issued not in repr(created)
    assert created.type is WebhookSecretType(secret_type)
    assert created.status is WebhookSecretStatus.CURRENT


def test_create_without_a_type_rotates(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        SECRETS_PATH,
        status=201,
        json_body=secret("5e6f7a8b", "current", secret="whsec_rotated"),
    )

    rotated = Connectors(fake_api.client()).secrets.create(CONNECTOR_UUID)

    # A rotation names no type: the server keeps the live secret's.
    assert fake_api.last_request.json() == {}
    assert rotated.id == "5e6f7a8b"
    assert rotated.secret.get_secret_value() == "whsec_rotated"


def test_create_rejects_an_unknown_secret_type_before_sending(
    fake_api: FakeAPI,
):
    with pytest.raises(PydanticValidationError, match="type"):
        Connectors(fake_api.client()).secrets.create(
            CONNECTOR_UUID, type="mtls"
        )
    assert fake_api.requests == []


@pytest.mark.parametrize(
    "detail",
    [
        "Two secrets are live; delete one first",
        "A live secret is standard_webhooks; delete every secret first",
    ],
)
def test_create_conflict_surfaces_the_409(fake_api: FakeAPI, detail: str):
    fake_api.add(
        "POST", SECRETS_PATH, status=409, json_body={"detail": detail}
    )

    with pytest.raises(ConflictError, match=detail):
        Connectors(fake_api.client()).secrets.create(
            CONNECTOR_UUID, type="bearer"
        )


def test_create_without_a_type_and_none_live_surfaces_the_422(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        SECRETS_PATH,
        status=422,
        json_body={"detail": "Name a type for the first secret"},
    )

    with pytest.raises(ValidationError):
        Connectors(fake_api.client()).secrets.create(CONNECTOR_UUID)


def test_secrets_of_a_non_webhook_connector_surface_the_404(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        SECRETS_PATH,
        status=404,
        json_body={"detail": "Not a webhook connector"},
    )

    with pytest.raises(NotFoundError):
        list(Connectors(fake_api.client()).secrets.list(CONNECTOR_UUID))


def test_delete_a_webhook_secret_by_kid(fake_api: FakeAPI):
    fake_api.add("DELETE", f"{SECRETS_PATH}/5e6f7a8b", status=204)

    result = Connectors(fake_api.client()).secrets.delete(
        CONNECTOR_UUID, "5e6f7a8b"
    )

    assert result is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.path == f"{SECRETS_PATH}/5e6f7a8b"
    assert fake_api.last_request.content == b""


def test_delete_the_current_secret_while_a_previous_is_live_surfaces_the_409(
    fake_api: FakeAPI,
):
    fake_api.add(
        "DELETE",
        f"{SECRETS_PATH}/5e6f7a8b",
        status=409,
        json_body={"detail": "Delete the previous secret first"},
    )

    with pytest.raises(ConflictError):
        Connectors(fake_api.client()).secrets.delete(
            CONNECTOR_UUID, "5e6f7a8b"
        )


def test_delete_an_unknown_secret_surfaces_the_404(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        Connectors(fake_api.client()).secrets.delete(
            CONNECTOR_UUID, "00000000"
        )
    assert fake_api.last_request.path == f"{SECRETS_PATH}/00000000"


@pytest.mark.parametrize(
    "removed", ["rotate_signing_secret", "revoke_signing_secret"]
)
def test_update_no_longer_takes_secret_actions(
    fake_api: FakeAPI, removed: str
):
    connectors = Connectors(fake_api.client())

    with pytest.raises(TypeError, match=removed):
        connectors.update(CONNECTOR_UUID, **{removed: True})  # type: ignore[arg-type]
    assert removed not in ConnectorUpdateRequest.model_fields
    assert fake_api.requests == []


def test_an_update_returns_a_connector(fake_api: FakeAPI):
    fake_api.add("PATCH", CONNECTOR_PATH, json_body=webhook_payload())

    updated = Connectors(fake_api.client()).update(
        CONNECTOR_UUID, name="Orders (EU)"
    )

    assert fake_api.last_request.json() == {"name": "Orders (EU)"}
    assert type(updated) is Connector


async def test_async_webhook_secrets_create_list_and_delete(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        SECRETS_PATH,
        status=201,
        json_body=secret(
            "1a2b3c4d", "current", type="bearer", secret="whtok_a"
        ),
    )
    fake_api.add(
        "GET",
        SECRETS_PATH,
        json_body=secret_page(secret("1a2b3c4d", "current", type="bearer")),
    )
    fake_api.add("DELETE", f"{SECRETS_PATH}/1a2b3c4d", status=204)
    secrets = AsyncConnectors(fake_api.async_client()).secrets

    created = await secrets.create(
        CONNECTOR_UUID, type=WebhookSecretType.BEARER
    )
    assert type(created) is WebhookSecretCreated
    assert created.secret.get_secret_value() == "whtok_a"
    listed = [s async for s in secrets.list(CONNECTOR_UUID)]
    assert [s.id for s in listed] == ["1a2b3c4d"]
    await secrets.delete(CONNECTOR_UUID, "1a2b3c4d")

    assert [(r.method, r.path) for r in fake_api.requests] == [
        ("POST", SECRETS_PATH),
        ("GET", SECRETS_PATH),
        ("DELETE", f"{SECRETS_PATH}/1a2b3c4d"),
    ]
    assert fake_api.requests[0].json() == {"type": "bearer"}


async def test_async_create_without_a_type_and_none_live_surfaces_the_422(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        SECRETS_PATH,
        status=422,
        json_body={"detail": "Name a type for the first secret"},
    )

    with pytest.raises(ValidationError):
        await AsyncConnectors(fake_api.async_client()).secrets.create(
            CONNECTOR_UUID
        )


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


def test_authorize_installs_an_organization_integration(fake_api: FakeAPI):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )
    integration_id = UUID("44444444-4444-4444-4444-444444444444")

    minted = Connectors(fake_api.client()).authorize(
        None, integration_id=integration_id, return_url="ark://connected"
    )

    assert minted.authorize_url
    assert fake_api.last_request.json() == {
        "integration_id": str(integration_id),
        "return_url": "ark://connected",
    }


async def test_async_authorize_installs_an_organization_integration(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST", AUTHORIZE_PATH, json_body=connector_authorization_payload()
    )
    integration_id = UUID("44444444-4444-4444-4444-444444444444")

    await AsyncConnectors(fake_api.async_client()).authorize(
        None, integration_id=integration_id
    )

    assert fake_api.last_request.json() == {
        "integration_id": str(integration_id)
    }


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
    assert discovered.revocation_endpoint == "https://mcp.linear.app/revoke"


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
    assert discovered.revocation_endpoint is None
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


# --- token broker ---------------------------------------------------


def test_get_token_returns_provider_token(fake_api: FakeAPI):
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
    result = Connectors(fake_api.client()).get_token(
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


def test_get_token_preserves_pending_mission(fake_api: FakeAPI):
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
    result = Connectors(fake_api.client()).get_token(
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


async def test_async_aauth_create_and_policy_update(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/connectors", json_body=connector_payload())
    fake_api.add("PATCH", CONNECTOR_PATH, json_body=connector_payload())
    connectors = AsyncConnectors(fake_api.async_client())

    await connectors.create(
        name="Bookings",
        provider="booking",
        auth_mode="aauth",
        person_server_url="https://person.example.com",
        application_id=UUID(APPLICATION_ID),
        policy_entities=[ACME_ENTITY],
    )
    assert fake_api.last_request.json()["policy_entities"] == [ACME_ENTITY]
    assert fake_api.last_request.json()["auth_mode"] == "aauth"

    await connectors.update(CONNECTOR_UUID, policy_entities=[])
    assert fake_api.last_request.json() == {"policy_entities": []}


async def test_async_get_token(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        json_body={
            "token": "provider-token",
            "token_type": "bearer",
            "scopes": [],
        },
    )
    result = await AsyncConnectors(fake_api.async_client()).get_token(
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


def test_list_and_delete_name_the_project(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/connectors", json_body=paginated([connector_payload()])
    )
    fake_api.add("DELETE", CONNECTOR_PATH, status=204)
    connectors = Connectors(fake_api.client())
    assert len(connectors.list(project="support").page().records) == 1
    assert fake_api.last_request.params.get("project") == "support"
    connectors.delete(CONNECTOR_UUID, project="support")
    assert fake_api.last_request.params.get("project") == "support"


async def test_async_list_and_delete_name_the_project(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/connectors", json_body=paginated([connector_payload()])
    )
    fake_api.add("DELETE", CONNECTOR_PATH, status=204)
    connectors = AsyncConnectors(fake_api.async_client())
    page = await connectors.list(project="support")
    assert len(page.records) == 1
    await connectors.delete(CONNECTOR_UUID)
    assert "project" not in fake_api.last_request.params
