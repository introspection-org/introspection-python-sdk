"""Contract tests for native email-code sign-in (:mod:`introspection_sdk.auth`).

Driven through the offline :class:`FakeAPI` transport: the fake serves the
Control Plane's ``/v1/oauth/email/code``, ``/v1/oauth/token`` and
``/v1/oauth/revoke`` plus a Data Plane route, and the tests assert the wire
requests the SDK builds and how the session moves between them. Time is
injected through ``clock`` so expiry is exact.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from introspection_sdk import (
    AsyncEmailCodeAuth,
    AuthenticationError,
    AuthSession,
    EmailCodeAuth,
    NetworkError,
    OAuthToken,
    RateLimitError,
    SignInSupersededError,
    ValidationError,
)
from introspection_sdk.auth import GRANT_EMAIL_CODE, revoke_session

from .conftest import ORG_ID, PROJECT_ID, FakeAPI, paginated

CLIENT_ID = "intro_app_native"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _jwt(claims: dict[str, Any]) -> str:
    def seg(value: dict[str, Any]) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(value).encode())
        return raw.decode().rstrip("=")

    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


def _token_body(access: str, refresh: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh,
        "scope": "tasks:read events:read",
        "session_id": "sess-1",
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "member_id": MEMBER_ID,
        "dp_url": "https://dp.example.test",
    }
    body.update(overrides)
    return body


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class TokenEndpoint:
    """Answers the token grants, recording each form it saw."""

    def __init__(self) -> None:
        self.forms: list[dict[str, str]] = []
        self.refreshes = 0
        self.refresh_response: httpx.Response | None = None
        self.on_refresh: Any = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = _form(request)
        self.forms.append(form)
        if form["grant_type"] == GRANT_EMAIL_CODE:
            return httpx.Response(
                200, json=_token_body("access-1", "refresh-1")
            )
        self.refreshes += 1
        if self.on_refresh is not None:
            self.on_refresh()
        if self.refresh_response is not None:
            return self.refresh_response
        # A refresh response carries no dp_url.
        return httpx.Response(
            200,
            json=_token_body(
                f"access-{self.refreshes + 1}",
                f"refresh-{self.refreshes + 1}",
                dp_url=None,
            ),
        )


@pytest.fixture
def token_endpoint(fake_api: FakeAPI) -> TokenEndpoint:
    endpoint = TokenEndpoint()
    fake_api.add_handler("POST", "/v1/oauth/token", endpoint)
    fake_api.add("POST", "/v1/oauth/email/code", status=202)
    fake_api.add("POST", "/v1/oauth/revoke", json_body={"status": "revoked"})
    return endpoint


def _auth(fake_api: FakeAPI, clock: Clock, **kwargs: Any) -> EmailCodeAuth:
    return EmailCodeAuth(
        CLIENT_ID,
        "ark",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
        clock=clock,
        **kwargs,
    )


def _async_auth(
    fake_api: FakeAPI, clock: Clock, **kwargs: Any
) -> AsyncEmailCodeAuth:
    return AsyncEmailCodeAuth(
        CLIENT_ID,
        "ark",
        base_api_url="https://api.test",
        transport=fake_api.transport(),
        clock=clock,
        **kwargs,
    )


def test_send_code_posts_json_to_email_code_route(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    _auth(fake_api, Clock()).send_code("user@example.com")

    assert fake_api.last_request.path == "/v1/oauth/email/code"
    assert fake_api.last_request.json() == {
        "client_id": CLIENT_ID,
        "email": "user@example.com",
        "project": "ark",
    }


def test_send_code_rate_limit_surfaces_retry_after(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/email/code",
        status=429,
        json_body={
            "error": "slow_down",
            "error_description": "Too many codes requested; try again later",
        },
        headers={"Retry-After": "30"},
    )

    with pytest.raises(RateLimitError) as info:
        _auth(fake_api, Clock()).send_code("user@example.com")

    assert info.value.code == "slow_down"
    assert info.value.retry_after == 30.0
    assert "Too many codes" in str(info.value)


def test_verify_code_accepts_letters_and_signs_in(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    changes: list[AuthSession | None] = []
    auth = _auth(fake_api, Clock(), on_session_change=changes.append)

    session = auth.verify_code("user@example.com", " H2DS00 ")

    assert token_endpoint.forms[-1] == {
        "grant_type": "urn:introspection:params:oauth:grant-type:email_code",
        "client_id": CLIENT_ID,
        "email": "user@example.com",
        "code": "H2DS00",
        "project": "ark",
    }
    assert session.access_token == "access-1"
    assert session.refresh_token == "refresh-1"
    assert session.session_id == "sess-1"
    assert session.member_id == MEMBER_ID
    assert session.dp_url == "https://dp.example.test"
    assert session.expires_at == NOW + timedelta(seconds=3600)
    assert changes == [session]
    assert auth.current_session == session


def test_verify_code_invalid_grant_is_typed(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/token",
        status=400,
        json_body={
            "error": "invalid_grant",
            "error_description": "The code is invalid or has expired",
        },
    )
    auth = _auth(fake_api, Clock())

    with pytest.raises(ValidationError) as info:
        auth.verify_code("user@example.com", "000000")

    assert info.value.code == "invalid_grant"
    assert str(info.value) == "The code is invalid or has expired"
    assert auth.current_session is None


def test_session_ids_fall_back_to_the_jwt_claims():
    access = _jwt({"jti": "sess-jwt", "org_id": ORG_ID, "member_id": "m-1"})
    token = OAuthToken(access_token=access, expires_in=60)

    session = AuthSession.from_token(token, received_at=NOW)

    assert session.session_id == "sess-jwt"
    assert session.org_id == ORG_ID
    assert session.member_id == "m-1"
    assert session.refresh_token is None


def test_get_session_refreshes_within_leeway_and_keeps_dp_url(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    clock = Clock()
    auth = _auth(fake_api, clock, leeway=60)
    auth.verify_code("user@example.com", "123456")

    clock.now = NOW + timedelta(seconds=3500)
    assert auth.get_session().access_token == "access-1"  # type: ignore[union-attr]
    assert token_endpoint.refreshes == 0

    clock.now = NOW + timedelta(seconds=3541)
    session = auth.get_session()

    assert token_endpoint.forms[-1] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
        "client_id": CLIENT_ID,
        "session_id": "sess-1",
        "org_id": ORG_ID,
    }
    assert session is not None
    assert session.access_token == "access-2"
    assert session.refresh_token == "refresh-2"
    assert session.dp_url == "https://dp.example.test"


def test_rejected_refresh_signs_out(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    changes: list[AuthSession | None] = []
    auth = _auth(fake_api, Clock(), on_session_change=changes.append)
    auth.verify_code("user@example.com", "123456")
    token_endpoint.refresh_response = httpx.Response(
        400,
        json={"error": "invalid_grant", "error_description": "expired"},
    )

    with pytest.raises(AuthenticationError) as info:
        auth.refresh()

    assert info.value.code == "invalid_grant"
    assert "no longer valid" in str(info.value)
    assert auth.current_session is None
    assert changes[-1] is None


def test_failed_refresh_that_is_not_a_rejection_keeps_the_session(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")
    token_endpoint.refresh_response = httpx.Response(
        503, json={"error": "temporarily_unavailable"}
    )

    with pytest.raises(Exception) as info:
        auth.refresh()

    assert not isinstance(info.value, AuthenticationError)
    assert auth.current_session is not None


def test_refresh_without_a_session_or_refresh_token_raises(fake_api: FakeAPI):
    auth = _auth(fake_api, Clock())
    with pytest.raises(AuthenticationError):
        auth.refresh()

    auth.set_session(OAuthToken(access_token="opaque", expires_in=60))
    with pytest.raises(AuthenticationError, match="no refresh token"):
        auth.refresh()


def test_superseded_sign_in_response_is_dropped(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    newer = AuthSession(access_token="newer")

    def sign_in_elsewhere(request: httpx.Request) -> httpx.Response:
        auth.set_session(newer)
        return httpx.Response(200, json=_token_body("stale", "stale-r"))

    fake_api.add_handler("POST", "/v1/oauth/token", sign_in_elsewhere)

    with pytest.raises(SignInSupersededError):
        auth.verify_code("user@example.com", "123456")

    assert auth.current_session is newer


def test_refresh_superseded_by_sign_out_is_dropped(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")
    token_endpoint.on_refresh = auth.sign_out

    with pytest.raises(SignInSupersededError):
        auth.refresh()

    assert auth.current_session is None


def test_sign_out_revokes_the_session(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    changes: list[AuthSession | None] = []
    auth = _auth(fake_api, Clock(), on_session_change=changes.append)
    auth.verify_code("user@example.com", "123456")

    auth.sign_out()

    assert fake_api.last_request.path == "/v1/oauth/revoke"
    assert _form_of(fake_api) == {
        "client_id": CLIENT_ID,
        "session_id": "sess-1",
        "org_id": ORG_ID,
    }
    assert auth.current_session is None
    assert changes[-1] is None
    auth.sign_out()  # signed out already: nothing to revoke


def test_sign_out_clears_locally_even_when_revoke_fails(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")
    fake_api.add(
        "POST",
        "/v1/oauth/revoke",
        status=400,
        json_body={"detail": "Invalid client_id"},
    )

    with pytest.raises(ValidationError):
        auth.sign_out()

    assert auth.current_session is None


def _form_of(fake_api: FakeAPI) -> dict[str, str]:
    parsed = parse_qs(fake_api.last_request.content.decode())
    return {k: v[0] for k, v in parsed.items()}


def test_client_renews_after_a_401_and_retries_once(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")
    seen: list[str | None] = []

    def automations(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if request.headers.get("authorization") == "Bearer access-1":
            return httpx.Response(401, json={"detail": "Token expired"})
        return httpx.Response(200, json=paginated([]).model_dump(mode="json"))

    fake_api.add_handler("GET", "/v1/automations", automations)
    client = auth.client()

    page = client.automations.list().page()

    assert page.records == []
    assert seen == ["Bearer access-1", "Bearer access-2"]
    assert str(client._dp_http._client.base_url).startswith(
        "https://dp.example.test"
    )
    assert token_endpoint.refreshes == 1


def test_client_does_not_loop_on_a_persistent_401(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")
    fake_api.add("GET", "/v1/automations", status=401, json_body={})

    with pytest.raises(AuthenticationError):
        auth.client().automations.list().page()

    assert token_endpoint.refreshes == 1


def test_a_401_for_an_older_token_only_retries(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _auth(fake_api, Clock())
    auth.verify_code("user@example.com", "123456")

    assert auth.refresh_after_unauthorized("Bearer older") is True
    assert token_endpoint.refreshes == 0


def test_client_requires_a_session(fake_api: FakeAPI):
    auth = _auth(fake_api, Clock())
    with pytest.raises(AuthenticationError):
        auth.client()
    assert auth.authorization() is None
    assert auth.refresh_after_unauthorized(None) is False


def test_restored_session_is_used_without_signing_in(fake_api: FakeAPI):
    restored = AuthSession.model_validate_json(
        AuthSession(
            access_token="kept",
            refresh_token="r",
            session_id="s",
            org_id=ORG_ID,
            expires_at=NOW + timedelta(hours=1),
        ).model_dump_json()
    )
    auth = _auth(fake_api, Clock(), session=restored)

    assert auth.authorization() == "Bearer kept"


def test_revoke_session_network_error_is_typed():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(NetworkError):
        revoke_session(
            "s",
            ORG_ID,
            CLIENT_ID,
            base_api_url="https://api.test",
            transport=httpx.MockTransport(boom),
        )


# --- async ------------------------------------------------------------


async def test_async_sign_in_refresh_and_sign_out(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    clock = Clock()
    changes: list[AuthSession | None] = []
    auth = _async_auth(fake_api, clock, on_session_change=changes.append)

    await auth.send_code("user@example.com")
    session = await auth.verify_code("user@example.com", "A1B2C3")
    assert token_endpoint.forms[-1]["code"] == "A1B2C3"
    assert session.access_token == "access-1"

    clock.now = NOW + timedelta(hours=1)
    refreshed = await auth.get_session()
    assert refreshed is not None
    assert refreshed.access_token == "access-2"
    assert refreshed.dp_url == "https://dp.example.test"

    await auth.sign_out()
    assert fake_api.last_request.path == "/v1/oauth/revoke"
    assert auth.current_session is None
    assert changes[-1] is None


async def test_async_concurrent_refreshes_share_one_request(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _async_auth(fake_api, Clock())
    await auth.verify_code("user@example.com", "123456")

    async def slow_refresh(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return token_endpoint(request)

    fake_api.add_handler("POST", "/v1/oauth/token", slow_refresh)  # type: ignore[arg-type]

    first, second = await asyncio.gather(auth.refresh(), auth.refresh())

    assert first is second
    assert token_endpoint.refreshes == 1


async def test_async_client_renews_after_a_401(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _async_auth(fake_api, Clock())
    await auth.verify_code("user@example.com", "123456")

    def automations(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") == "Bearer access-1":
            return httpx.Response(401, json={"detail": "Token expired"})
        return httpx.Response(200, json=paginated([]).model_dump(mode="json"))

    fake_api.add_handler("GET", "/v1/automations", automations)
    client = await auth.client()

    page = await client.automations.list()

    assert page.records == []
    assert token_endpoint.refreshes == 1
    assert await auth.refresh_after_unauthorized("Bearer older") is True


async def test_async_rejected_refresh_signs_out(
    fake_api: FakeAPI, token_endpoint: TokenEndpoint
):
    auth = _async_auth(fake_api, Clock())
    await auth.verify_code("user@example.com", "123456")
    token_endpoint.refresh_response = httpx.Response(
        401, json={"detail": "User account has been deleted"}
    )

    with pytest.raises(AuthenticationError, match="no longer valid"):
        await auth.refresh()

    assert auth.current_session is None
    with pytest.raises(AuthenticationError):
        await auth.client()


async def test_async_superseded_sign_in_is_dropped(fake_api: FakeAPI):
    auth = _async_auth(fake_api, Clock())

    def sign_in_elsewhere(request: httpx.Request) -> httpx.Response:
        auth.set_session(OAuthToken(access_token="newer", expires_in=60))
        return httpx.Response(200, json=_token_body("stale", "stale-r"))

    fake_api.add_handler("POST", "/v1/oauth/token", sign_in_elsewhere)

    with pytest.raises(SignInSupersededError):
        await auth.verify_code("user@example.com", "123456")

    assert auth.current_session is not None
    assert auth.current_session.access_token == "newer"
