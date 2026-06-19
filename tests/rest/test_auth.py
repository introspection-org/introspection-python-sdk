"""Contract tests for the server-side OAuth helpers in
:mod:`introspection_sdk.auth`.

Drives the helpers through :class:`httpx.MockTransport` (the shared
``FakeAPI`` route table) — no SDK internals are patched. The fake serves
``POST /v1/oauth/token`` and the tests assert the form body the SDK
builds (grant type / credentials / scope) and that the response parses
into a typed :class:`OAuthToken` carrying ``dp_url``.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from introspection_sdk import (
    AsyncIntrospectionClient,
    IntrospectionClient,
    NetworkError,
    OAuthToken,
    ValidationError,
    async_service_account_token,
    authorization_code_token,
    service_account_token,
    token_exchange,
)
from introspection_sdk.auth import (
    async_authorization_code_token,
    async_token_exchange,
)

from .conftest import FakeAPI


def _raising_transport() -> httpx.MockTransport:
    """A transport that fails at the socket level (DNS/TCP/TLS), to drive
    the ``NetworkError`` translation branch."""

    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return httpx.MockTransport(_boom)


_TOKEN_BODY = {
    "access_token": "minted-access-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "runtimes:run",
    "dp_url": "https://dp.example.test",
    # Extra wire fields the CP returns are tolerated (extra="allow").
    "project_id": "00000000-0000-0000-0000-0000000000bb",
}


def _form(fake: FakeAPI) -> dict[str, str]:
    parsed = parse_qs(fake.last_request.content.decode())
    return {k: v[0] for k, v in parsed.items()}


# --- service account (client_credentials) ---------------------------


def test_service_account_token_builds_form_and_parses(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    token = service_account_token(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        scope="runtimes:run",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert isinstance(token, OAuthToken)
    assert token.access_token == "minted-access-token"
    assert token.dp_url == "https://dp.example.test"
    assert fake_api.last_request.path == "/v1/oauth/token"
    form = _form(fake_api)
    assert form == {
        "grant_type": "client_credentials",
        "client_id": "intro_app_123",
        "client_secret": "intro_sk_456",
        "project_id": "proj-1",
        "scope": "runtimes:run",
    }


def test_service_account_token_omits_empty_scope(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    service_account_token(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert "scope" not in _form(fake_api)


def test_service_account_token_maps_errors(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/token",
        status=400,
        json_body={"detail": "invalid_client", "code": "invalid_client"},
    )

    with pytest.raises(ValidationError):
        service_account_token(
            client_id="bad",
            client_secret="bad",
            project_id="proj-1",
            base_api_url="https://api.test",
            transport=fake_api.transport(),
        )


# --- token exchange (RFC 8693) --------------------------------------


def test_token_exchange_defaults_subject_token_type(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    token_exchange(
        subject_token="partner-id-token",
        client_id="intro_app_fed",
        project_id="proj-1",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    form = _form(fake_api)
    assert form["grant_type"] == (
        "urn:ietf:params:oauth:grant-type:token-exchange"
    )
    assert form["subject_token"] == "partner-id-token"
    assert form["subject_token_type"] == (
        "urn:ietf:params:oauth:token-type:id_token"
    )
    assert "scope" not in form


def test_token_exchange_includes_scope(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    token_exchange(
        subject_token="partner-id-token",
        client_id="intro_app_fed",
        project_id="proj-1",
        scope="runtimes:run files:read",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert _form(fake_api)["scope"] == "runtimes:run files:read"


# --- authorization code (PKCE) --------------------------------------


def test_authorization_code_token_builds_form(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    authorization_code_token(
        code="auth-code",
        client_id="intro_app_spa",
        redirect_uri="http://localhost:3200/callback",
        code_verifier="verifier-xyz",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    form = _form(fake_api)
    assert form == {
        "grant_type": "authorization_code",
        "code": "auth-code",
        "client_id": "intro_app_spa",
        "redirect_uri": "http://localhost:3200/callback",
        "code_verifier": "verifier-xyz",
    }


# --- base URL resolution --------------------------------------------


def test_base_api_url_falls_back_to_env(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("INTROSPECTION_BASE_API_URL", "https://api.test")
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    token = service_account_token(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        transport=fake_api.transport(),
    )

    assert token.access_token == "minted-access-token"


# --- from_service_account constructors ------------------------------


def test_from_service_account_wires_token(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    client = IntrospectionClient.from_service_account(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert client._token == "minted-access-token"
    assert client._base_api_url == "https://api.test"
    client.shutdown()


# --- async twins -----------------------------------------------------


@pytest.mark.asyncio
async def test_async_service_account_token(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    token = await async_service_account_token(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert token.access_token == "minted-access-token"
    assert _form(fake_api)["grant_type"] == "client_credentials"


@pytest.mark.asyncio
async def test_async_token_exchange(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    await async_token_exchange(
        subject_token="partner-id-token",
        client_id="intro_app_fed",
        project_id="proj-1",
        subject_token_type="urn:custom:token",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert _form(fake_api)["subject_token_type"] == "urn:custom:token"


@pytest.mark.asyncio
async def test_async_authorization_code_token(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    await async_authorization_code_token(
        code="auth-code",
        client_id="intro_app_spa",
        redirect_uri="http://localhost:3200/callback",
        code_verifier="verifier-xyz",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert _form(fake_api)["grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_async_from_service_account_wires_token(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/token", json_body=_TOKEN_BODY)

    client = await AsyncIntrospectionClient.from_service_account(
        client_id="intro_app_123",
        client_secret="intro_sk_456",
        project_id="proj-1",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
    )

    assert client._token == "minted-access-token"
    await client.shutdown()


@pytest.mark.asyncio
async def test_async_token_maps_http_errors(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/token",
        status=400,
        json_body={"detail": "invalid_client", "code": "invalid_client"},
    )

    with pytest.raises(ValidationError):
        await async_service_account_token(
            client_id="bad",
            client_secret="bad",
            project_id="proj-1",
            base_api_url="https://api.test",
            transport=fake_api.transport(),
        )


# --- transport-level failures ---------------------------------------


def test_service_account_token_wraps_network_errors():
    with pytest.raises(NetworkError):
        service_account_token(
            client_id="intro_app_123",
            client_secret="intro_sk_456",
            project_id="proj-1",
            base_api_url="https://api.test",
            transport=_raising_transport(),
        )


@pytest.mark.asyncio
async def test_async_service_account_token_wraps_network_errors():
    with pytest.raises(NetworkError):
        await async_service_account_token(
            client_id="intro_app_123",
            client_secret="intro_sk_456",
            project_id="proj-1",
            base_api_url="https://api.test",
            transport=_raising_transport(),
        )
