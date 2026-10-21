"""Contract tests for the project administration namespaces.

``projects``, ``api_keys``, ``applications`` (with ``idps`` / ``secrets`` /
``keys``), ``credentials``, ``variables``, ``integrations``, ``judges`` and
``oidc``: each pins the path, the ``?project=`` selector, the body's wire
names, and that a secret the API returns once or takes on write never
prints.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk import IntrospectionClient
from introspection_sdk._errors import ConflictError, NotFoundError
from introspection_sdk.resources import (
    ApiKeys,
    Applications,
    AsyncApiKeys,
    AsyncApplications,
    Credentials,
    Integrations,
    Judges,
    Oidc,
    Projects,
    Variables,
)
from introspection_sdk.schemas.api_keys import (
    ApiKeyCapability,
    ApiKeyStatus,
)
from introspection_sdk.schemas.applications import ApplicationType
from introspection_sdk.schemas.integrations import (
    IntegrationStatus,
    IntegrationType,
    IntegrationUpdateRequest,
)
from introspection_sdk.schemas.lanes import Environment
from introspection_sdk.schemas.runtime_settings import (
    CredentialCreateRequest,
    VariableKind,
)

from .conftest import (
    MEMBER_ID,
    ORG_ID,
    PROJECT_ID,
    RUNTIME_GROUP_ID,
    RUNTIME_ID,
    FakeAPI,
)

NOW = "2026-10-21T12:00:00Z"
KEY_ID = "0199a1b2-0000-7000-8000-0000000000a1"
APP_ID = "0199a1b2-0000-7000-8000-0000000000a2"
IDP_ID = "0199a1b2-0000-7000-8000-0000000000a3"
SECRET_ID = "0199a1b2-0000-7000-8000-0000000000a4"
SIGNING_KEY_ID = "0199a1b2-0000-7000-8000-0000000000a5"
CREDENTIAL_ID = "0199a1b2-0000-7000-8000-0000000000a6"
VARIABLE_ID = "0199a1b2-0000-7000-8000-0000000000a7"
INTEGRATION_ID = "0199a1b2-0000-7000-8000-0000000000a8"
JUDGE_ID = "0199a1b2-0000-7000-8000-0000000000a9"
DEPLOYMENT_ID = "0199a1b2-0000-7000-8000-0000000000aa"
PLAINTEXT = "intro_sk_plaintext_never_printed"


def page(*records: dict[str, Any], next: str | None = None) -> dict:
    return {"records": list(records), "count": len(records), "next": next}


def project_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "org_id": ORG_ID,
        "deployment_id": DEPLOYMENT_ID,
        "name": "Support",
        "slug": "support",
        "description": None,
        **over,
    }


def api_key_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": KEY_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": NOW,
        "name": "ci",
        "environment": "development",
        "allow": ["evals"],
        "scope": "*",
        "key_prefix": "intro_dev_",
        "key_suffix": "abcd",
        "status": "active",
        "key_display": "intro_dev_...abcd",
        "prefix": "intro_dev_",
        **over,
    }


def application_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": APP_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "name": "backend",
        "application_type": "service_account",
        "environment": "production",
        "client_id": "app_client",
        "allowed_grants": ["client_credentials"],
        "created_by_member_id": MEMBER_ID,
        **over,
    }


def credential_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": CREDENTIAL_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "name": "OPENAI_API_KEY",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "environment": None,
        "has_secret": True,
        "secret_display": "sk-...wxyz",
        "created_by_member_id": MEMBER_ID,
        **over,
    }


def variable_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": VARIABLE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "name": "LOG_LEVEL",
        "kind": "value",
        "value": "debug",
        "created_by_member_id": MEMBER_ID,
        **over,
    }


def integration_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": INTEGRATION_ID,
        "org_id": ORG_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "type": "custom",
        "name": "internal",
        "status": "pending",
        "created_by_member_id": MEMBER_ID,
        **over,
    }


def judge_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": JUDGE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "name": "helpfulness",
        "enabled": True,
        "sample_rate": 0.5,
        "source": "recipe",
        "definition_hash": "sha256:abc",
        **over,
    }


# --- client wiring ---------------------------------------------------


def test_client_hangs_every_namespace_off_the_control_plane():
    client = IntrospectionClient(
        token="t",
        base_api_url="https://cp.test",
        dp_url="https://dp.test",
    )
    try:
        for name in (
            "projects",
            "api_keys",
            "applications",
            "credentials",
            "variables",
            "integrations",
            "judges",
            "oidc",
        ):
            namespace = getattr(client, name)
            assert namespace._http is client._http, name
        assert client.images._http is client._dp_http
        assert client.tasks.commands._http is client._dp_http
    finally:
        client.shutdown()


# --- projects --------------------------------------------------------


def test_project_get_percent_encodes_the_slug(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/projects/acme/support desk", json_body=project_payload()
    )

    project = Projects(fake_api.client()).get("acme/support desk")

    assert project.slug == "support"
    assert (
        fake_api.last_request.url.raw_path
        == b"/v1/projects/acme%2Fsupport%20desk"
    )


def test_project_get_by_id_and_missing_is_typed(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/projects/{PROJECT_ID}", json_body=project_payload()
    )
    projects = Projects(fake_api.client())

    assert projects.get(UUID(PROJECT_ID)).deployment_id == UUID(DEPLOYMENT_ID)
    with pytest.raises(NotFoundError):
        projects.get("gone")


def test_project_list_pages_and_narrows_by_project(fake_api: FakeAPI):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("next") == "c2":
            body = page(project_payload(id=DEPLOYMENT_ID, slug="two"))
        else:
            body = page(project_payload(), next="c2")
        return httpx.Response(200, json=body)

    fake_api.add_handler("GET", "/v1/projects", handler)

    slugs = [
        p.slug for p in Projects(fake_api.client()).list(project="support")
    ]

    assert slugs == ["support", "two"]
    first, second = fake_api.requests
    assert first.params.get("project") == "support"
    assert "next" not in first.params
    assert second.params.get("next") == "c2"


def test_projects_has_no_writes():
    # projects:write / projects:delete are in no API-key, service-account or
    # CLI-login ceiling, so the SDK exposes reads only.
    for verb in ("create", "update", "delete"):
        assert not hasattr(Projects, verb)


# --- oidc ------------------------------------------------------------


def test_oidc_me_keeps_each_feature_flag_type(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/oidc/me",
        json_body={
            "authenticated": True,
            "org_id": ORG_ID,
            "member_id": MEMBER_ID,
            "email": "owner@example.com",
            "feature_flags": {
                "evals": True,
                "max_runtimes": 3,
                "ratio": 0.25,
                "tier": "pro",
            },
        },
    )

    me = Oidc(fake_api.client()).me()

    assert me.member_id == UUID(MEMBER_ID)
    assert me.feature_flags == {
        "evals": True,
        "max_runtimes": 3,
        "ratio": 0.25,
        "tier": "pro",
    }
    assert type(me.feature_flags["evals"]) is bool
    assert type(me.feature_flags["max_runtimes"]) is int


# --- api keys --------------------------------------------------------


def test_api_key_list_unwraps_the_envelope_and_sends_filters(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET", "/v1/api-keys", json_body={"api_keys": [api_key_payload()]}
    )

    keys = ApiKeys(fake_api.client()).list(project="support", expiring=True)

    assert [k.id for k in keys] == [UUID(KEY_ID)]
    assert keys[0].allow == [ApiKeyCapability.EVALS]
    assert dict(fake_api.last_request.params) == {
        "project": "support",
        "expiring": "true",
    }


def test_api_key_create_returns_a_redacted_plaintext(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/api-keys",
        status=201,
        json_body=api_key_payload(api_key=PLAINTEXT),
    )

    created = ApiKeys(fake_api.client()).create(
        project="support",
        name="ci",
        environment=Environment.DEVELOPMENT,
        allow=["evals"],
    )

    assert fake_api.last_request.json() == {
        "name": "ci",
        "environment": "development",
        "allow": ["evals"],
    }
    assert fake_api.last_request.params.get("project") == "support"
    assert isinstance(created.api_key, SecretStr)
    assert created.api_key.get_secret_value() == PLAINTEXT
    assert PLAINTEXT not in repr(created)
    assert PLAINTEXT not in str(created)
    assert PLAINTEXT not in created.model_dump_json()


def test_api_key_update_delete_and_acknowledge(fake_api: FakeAPI):
    path = f"/v1/api-keys/{KEY_ID}"
    fake_api.add("PATCH", path, json_body=api_key_payload(name="renamed"))
    fake_api.add("DELETE", path, status=204)
    fake_api.add(
        "POST", f"{path}/acknowledge", json_body={"acknowledged": True}
    )
    keys = ApiKeys(fake_api.client())

    updated = keys.update(UUID(KEY_ID), name="renamed")
    assert updated.name == "renamed"
    assert fake_api.last_request.json() == {"name": "renamed"}
    assert "project" not in fake_api.last_request.params

    keys.delete(UUID(KEY_ID), project="support", expires_in=3600)
    assert dict(fake_api.last_request.params) == {
        "project": "support",
        "expires_in": "3600",
    }

    assert keys.acknowledge(UUID(KEY_ID), project="support").acknowledged
    assert fake_api.last_request.content == b""
    assert fake_api.last_request.params.get("project") == "support"


def test_api_key_delete_without_grace_sends_no_expiry(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/api-keys/{KEY_ID}", status=204)

    ApiKeys(fake_api.client()).delete(UUID(KEY_ID))

    assert dict(fake_api.last_request.params) == {}


def test_api_key_rotating_status_parses(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/api-keys",
        json_body={"api_keys": [api_key_payload(status="rotating")]},
    )

    (key,) = ApiKeys(fake_api.client()).list()

    assert key.status is ApiKeyStatus.ROTATING


async def test_async_api_keys_create(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/api-keys",
        status=201,
        json_body=api_key_payload(api_key=PLAINTEXT),
    )

    created = await AsyncApiKeys(fake_api.async_client()).create(name="ci")

    assert created.api_key is not None
    assert PLAINTEXT not in repr(created)
    assert fake_api.last_request.json() == {"name": "ci"}


# --- applications ----------------------------------------------------


def test_application_crud(fake_api: FakeAPI):
    path = f"/v1/applications/{APP_ID}"
    fake_api.add(
        "POST", "/v1/applications", status=201, json_body=application_payload()
    )
    fake_api.add("GET", path, json_body=application_payload())
    fake_api.add("PATCH", path, json_body=application_payload(name="b2"))
    fake_api.add("DELETE", path, status=204)
    fake_api.add(
        "GET", "/v1/applications", json_body=page(application_payload())
    )
    applications = Applications(fake_api.client())

    created = applications.create(
        name="backend",
        application_type=ApplicationType.SERVICE_ACCOUNT,
        project="support",
        allowed_scopes=["tasks:write"],
    )
    assert created.application_type is ApplicationType.SERVICE_ACCOUNT
    assert fake_api.last_request.json() == {
        "name": "backend",
        "application_type": "service_account",
        "allowed_scopes": ["tasks:write"],
    }
    assert fake_api.last_request.params.get("project") == "support"

    applications.get(UUID(APP_ID), project="support")
    assert fake_api.last_request.params.get("project") == "support"

    applications.update(UUID(APP_ID), name="b2", redirect_uris=[])
    # An explicit [] replaces the list, so it must reach the wire.
    assert fake_api.last_request.json() == {"name": "b2", "redirect_uris": []}

    listed = list(applications.list(project="support", limit=10))
    assert [a.id for a in listed] == [UUID(APP_ID)]
    assert fake_api.last_request.params.get("limit") == "10"

    applications.delete(UUID(APP_ID), project="support")
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.params.get("project") == "support"


def test_application_idps_send_the_secret_and_never_print_it(
    fake_api: FakeAPI,
):
    idps_path = f"/v1/applications/{APP_ID}/idps"
    idp = {
        "id": IDP_ID,
        "org_id": ORG_ID,
        "application_id": APP_ID,
        "idp_provider": "okta",
        "issuer": "https://idp.example.com",
        "client_id": "okta-client",
        "client_secret": PLAINTEXT,
        "is_active": False,
    }
    fake_api.add("POST", idps_path, status=201, json_body=idp)
    fake_api.add("GET", idps_path, json_body=page(idp))
    fake_api.add("DELETE", f"{idps_path}/{IDP_ID}", status=204)
    idps = Applications(fake_api.client()).idps

    created = idps.create(
        UUID(APP_ID),
        idp_provider="okta",
        issuer="https://idp.example.com",
        client_id="okta-client",
        client_secret=SecretStr(PLAINTEXT),
    )

    assert fake_api.last_request.json() == {
        "idp_provider": "okta",
        "issuer": "https://idp.example.com",
        "client_id": "okta-client",
        "client_secret": PLAINTEXT,
    }
    assert PLAINTEXT not in repr(created)
    assert [i.id for i in idps.list(UUID(APP_ID))] == [UUID(IDP_ID)]
    idps.delete(UUID(APP_ID), UUID(IDP_ID))
    assert fake_api.last_request.path == f"{idps_path}/{IDP_ID}"


def test_application_secrets_redact_the_one_time_plaintext(
    fake_api: FakeAPI,
):
    secrets_path = f"/v1/applications/{APP_ID}/secrets"
    secret = {
        "id": SECRET_ID,
        "org_id": ORG_ID,
        "application_id": APP_ID,
        "secret_prefix": "intro_sk_",
        "secret_suffix": "wxyz",
        "name": "deploy",
        "created_by_member_id": MEMBER_ID,
        "status": "active",
    }
    fake_api.add(
        "POST",
        secrets_path,
        status=201,
        json_body={**secret, "secret": PLAINTEXT},
    )
    fake_api.add("GET", secrets_path, json_body=page(secret))
    fake_api.add("DELETE", f"{secrets_path}/{SECRET_ID}", status=204)
    secrets = Applications(fake_api.client()).secrets

    created = secrets.create(UUID(APP_ID), name="deploy")
    assert fake_api.last_request.json() == {"name": "deploy"}
    assert created.secret is not None
    assert created.secret.get_secret_value() == PLAINTEXT
    assert PLAINTEXT not in repr(created)

    (listed,) = list(secrets.list(UUID(APP_ID)))
    assert listed.secret is None

    secrets.delete(UUID(APP_ID), UUID(SECRET_ID), expires_in=60)
    assert dict(fake_api.last_request.params) == {"expires_in": "60"}


def test_application_keys_are_an_unpaginated_array(fake_api: FakeAPI):
    keys_path = f"/v1/applications/{APP_ID}/keys"
    key = {
        "id": SIGNING_KEY_ID,
        "org_id": ORG_ID,
        "application_id": APP_ID,
        "kid": "k1",
        "algorithm": "RS256",
        "public_key": "-----BEGIN PUBLIC KEY-----",
    }
    fake_api.add("GET", keys_path, json_body=[key])
    fake_api.add("POST", keys_path, status=201, json_body=key)
    fake_api.add("DELETE", f"{keys_path}/{SIGNING_KEY_ID}", status=204)
    keys = Applications(fake_api.client()).keys

    assert [k.kid for k in keys.list(UUID(APP_ID))] == ["k1"]
    assert keys.create(UUID(APP_ID)).algorithm == "RS256"
    assert fake_api.last_request.content == b""
    keys.delete(UUID(APP_ID), UUID(SIGNING_KEY_ID))
    assert fake_api.last_request.method == "DELETE"


async def test_async_application_sub_namespaces(fake_api: FakeAPI):
    keys_path = f"/v1/applications/{APP_ID}/keys"
    fake_api.add("GET", keys_path, json_body=[])
    fake_api.add(
        "GET",
        f"/v1/applications/{APP_ID}/secrets",
        json_body=page(),
    )
    applications = AsyncApplications(fake_api.async_client())

    assert await applications.keys.list(UUID(APP_ID)) == []
    assert [s async for s in applications.secrets.list(UUID(APP_ID))] == []


# --- credentials -----------------------------------------------------


def test_credential_create_sends_the_plaintext_once(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/credentials", json_body=credential_payload())

    created = Credentials(fake_api.client()).create(
        name="OPENAI_API_KEY",
        secret="sk-live-value",
        project="support",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
    )

    assert fake_api.last_request.json() == {
        "name": "OPENAI_API_KEY",
        "secret": "sk-live-value",
        "runtime_group_id": RUNTIME_GROUP_ID,
    }
    assert created.has_secret
    assert not hasattr(created, "secret")


def test_credential_request_never_prints_the_secret():
    request = CredentialCreateRequest(name="K", secret=SecretStr("sk-live"))

    assert "sk-live" not in repr(request)
    assert request.model_dump(mode="json")["secret"] == "sk-live"


def test_credential_list_get_update_delete(fake_api: FakeAPI):
    path = f"/v1/credentials/{CREDENTIAL_ID}"
    fake_api.add(
        "GET", "/v1/credentials", json_body=page(credential_payload())
    )
    fake_api.add("GET", path, json_body=credential_payload())
    fake_api.add("PATCH", path, json_body=credential_payload())
    fake_api.add("DELETE", path, status=204)
    credentials = Credentials(fake_api.client())

    list(
        credentials.list(
            project="support",
            runtime_id=UUID(RUNTIME_ID),
            runtime="support-agent",
            environment=Environment.STAGING,
        )
    )
    assert dict(fake_api.last_request.params) == {
        "project": "support",
        "runtime_id": RUNTIME_ID,
        "runtime": "support-agent",
        "environment": "staging",
    }

    assert credentials.get(UUID(CREDENTIAL_ID)).runtime_group_id == UUID(
        RUNTIME_GROUP_ID
    )
    credentials.update(UUID(CREDENTIAL_ID), secret="sk-rotated")
    assert fake_api.last_request.json() == {"secret": "sk-rotated"}
    credentials.delete(UUID(CREDENTIAL_ID), project="support")
    assert fake_api.last_request.params.get("project") == "support"


# --- variables -------------------------------------------------------


def test_variable_crud(fake_api: FakeAPI):
    path = f"/v1/variables/{VARIABLE_ID}"
    fake_api.add("POST", "/v1/variables", json_body=variable_payload())
    fake_api.add("PATCH", path, json_body=variable_payload(value="info"))
    fake_api.add("DELETE", path, status=204)
    fake_api.add("GET", "/v1/variables", json_body=page(variable_payload()))
    variables = Variables(fake_api.client())

    created = variables.create(name="LOG_LEVEL", value="debug")
    # `kind` defaults server-side, so an omitted one stays off the wire.
    assert fake_api.last_request.json() == {
        "name": "LOG_LEVEL",
        "value": "debug",
    }
    assert created.kind is VariableKind.VALUE

    variables.create(
        name="OPENAI_API_KEY",
        kind=VariableKind.CREDENTIAL,
        value="OPENAI_API_KEY",
        environment="production",
    )
    assert fake_api.last_request.json() == {
        "name": "OPENAI_API_KEY",
        "kind": "credential",
        "value": "OPENAI_API_KEY",
        "environment": "production",
    }

    assert variables.update(UUID(VARIABLE_ID), value="info").value == "info"
    assert fake_api.last_request.json() == {"value": "info"}
    assert [v.name for v in variables.list(project="support")] == ["LOG_LEVEL"]
    variables.delete(UUID(VARIABLE_ID), project="support")
    assert fake_api.last_request.method == "DELETE"
    assert not hasattr(variables, "get")


def test_variable_rejects_an_unknown_lane_before_sending(fake_api: FakeAPI):
    with pytest.raises(PydanticValidationError):
        Variables(fake_api.client()).create(
            name="X", value="1", environment="qa"
        )
    assert fake_api.requests == []


# --- integrations ----------------------------------------------------


def test_integration_create_sends_the_wire_type(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/integrations",
        status=201,
        json_body=integration_payload(),
    )

    created = Integrations(fake_api.client()).create(
        integration_type=IntegrationType.CUSTOM, name="internal"
    )

    assert fake_api.last_request.json() == {
        "type": "custom",
        "name": "internal",
    }
    assert created.type is IntegrationType.CUSTOM
    assert created.status is IntegrationStatus.PENDING
    assert "project" not in fake_api.last_request.params


def test_integration_create_conflict_is_typed(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/integrations", status=409, json_body={"detail": "exists"}
    )

    with pytest.raises(ConflictError):
        Integrations(fake_api.client()).create(integration_type="github")


def test_integration_read_update_delete(fake_api: FakeAPI):
    path = f"/v1/integrations/{INTEGRATION_ID}"
    fake_api.add("GET", path, json_body=integration_payload())
    fake_api.add("PATCH", path, json_body=integration_payload(status="active"))
    fake_api.add("DELETE", path, status=204)
    fake_api.add(
        "GET", "/v1/integrations", json_body=page(integration_payload())
    )
    integrations = Integrations(fake_api.client())

    assert integrations.get(UUID(INTEGRATION_ID)).name == "internal"
    assert [i.id for i in integrations.list()] == [UUID(INTEGRATION_ID)]

    updated = integrations.update(
        UUID(INTEGRATION_ID),
        code="oauth-code",
        redirect_uri="https://app.test/cb",
        slack_interactivity_enabled=False,
    )
    assert updated.status is IntegrationStatus.ACTIVE
    # `False` is a value, not an omission, so it is sent.
    assert fake_api.last_request.json() == {
        "code": "oauth-code",
        "redirect_uri": "https://app.test/cb",
        "slack_interactivity_enabled": False,
    }
    integrations.delete(UUID(INTEGRATION_ID))
    assert fake_api.last_request.method == "DELETE"


def test_integration_oauth_code_never_prints():
    request = IntegrationUpdateRequest(code=SecretStr("oauth-code"))

    assert "oauth-code" not in repr(request)


# --- judges ----------------------------------------------------------


def test_judge_list_get_update(fake_api: FakeAPI):
    path = f"/v1/judges/{JUDGE_ID}"
    fake_api.add("GET", "/v1/judges", json_body=page(judge_payload()))
    fake_api.add("GET", path, json_body=judge_payload())
    fake_api.add("PATCH", path, json_body=judge_payload(enabled=False))
    judges = Judges(fake_api.client())

    listed = list(
        judges.list(project="support", runtime_group_id=UUID(RUNTIME_GROUP_ID))
    )
    assert [j.sample_rate for j in listed] == [0.5]
    assert dict(fake_api.last_request.params) == {
        "project": "support",
        "runtime_group_id": RUNTIME_GROUP_ID,
    }

    judges.get(UUID(JUDGE_ID), project="support")
    assert fake_api.last_request.params.get("project") == "support"

    updated = judges.update(UUID(JUDGE_ID), enabled=False, sample_rate=0.0)
    assert not updated.enabled
    assert fake_api.last_request.json() == {
        "enabled": False,
        "sample_rate": 0.0,
    }
    assert not hasattr(judges, "create")
    assert not hasattr(judges, "delete")


def test_judge_sample_rate_is_a_fraction(fake_api: FakeAPI):
    with pytest.raises(PydanticValidationError):
        Judges(fake_api.client()).update(UUID(JUDGE_ID), sample_rate=1.5)
    assert fake_api.requests == []
