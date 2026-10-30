"""Contract tests for the device-code login in :mod:`introspection_sdk.auth`
(CP ``POST /v1/oauth/device/code``, its token polls, the development
credential and ``GET /v1/oidc/logout``)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from introspection_sdk import (
    AuthenticationError,
    NetworkError,
    ValidationError,
)
from introspection_sdk.auth import (
    DEVICE_CODE_GRANT,
    DEVICE_FLOW_CLIENT_ID,
    AuthSession,
    DeviceCode,
    DeviceTokenStatus,
    OAuthToken,
    async_development_credential,
    async_oidc_logout,
    async_poll_device_token,
    async_request_device_code,
    async_wait_for_device_token,
    development_credential,
    oidc_logout,
    poll_device_token,
    refresh_access_token,
    request_device_code,
    wait_for_device_token,
)

from .conftest import FakeAPI

BASE = "https://api.test"
TOKEN_PATH = "/v1/oauth/token"

DEVICE = {
    "device_code": "dc-secret",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://app.test/activate",
    "verification_uri_complete": "https://app.test/activate?user_code=ABCD-EFGH",
    "expires_in": 600,
    "interval": 5,
}

# What the device-code grant answers once the member approves.
LOGIN = {
    "access_token": "login-access",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "login-refresh",
    "session_id": "sess-1",
    "org_id": "org-1",
    "project_id": "proj-1",
    "cp_session": "cookie-value",
    "cp_url": "https://api.test",
    "dp_url": "https://dp.test",
    "git_url": "https://git.test",
    "platform_url": "https://app.test",
    "member_id": "member-1",
    "member_name": "Walk Owner",
}


def oauth_error(code: str) -> dict[str, str]:
    return {"error": code, "error_description": code.replace("_", " ")}


def form(fake: FakeAPI) -> dict[str, str]:
    parsed = parse_qs(fake.last_request.content.decode())
    return {k: v[0] for k, v in parsed.items()}


def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(
        "introspection_sdk._sync.device_code._sleep", slept.append
    )
    return slept


def test_request_device_code_sends_the_form(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/device/code", json_body=DEVICE)
    device = request_device_code(
        project="walk",
        capabilities=["runtimes", "tasks"],
        base_api_url=BASE,
        transport=fake_api.transport(),
    )
    assert device.user_code == "ABCD-EFGH"
    assert device.device_code.get_secret_value() == "dc-secret"
    assert "dc-secret" not in repr(device), "the device code is a secret"
    assert device.verification_uri_complete.startswith(device.verification_uri)
    assert form(fake_api) == {
        "client_id": "cli",
        "project": "walk",
        "capabilities": "runtimes,tasks",
    }


def test_request_device_code_defaults(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/device/code",
        json_body={k: v for k, v in DEVICE.items() if k != "interval"},
    )
    device = request_device_code(
        base_api_url=BASE, transport=fake_api.transport()
    )
    assert device.interval == 5, "RFC 8628's default when the CP names none"
    assert form(fake_api) == {"client_id": "cli"}


def test_an_unknown_capability_is_refused(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/device/code",
        status=400,
        json_body=oauth_error("invalid_scope"),
    )
    with pytest.raises(ValidationError) as caught:
        request_device_code(
            capabilities=["nope"],
            base_api_url=BASE,
            transport=fake_api.transport(),
        )
    assert caught.value.code == "invalid_scope"


@pytest.mark.parametrize(
    "answer",
    [
        DeviceTokenStatus.PENDING,
        DeviceTokenStatus.SLOW_DOWN,
        DeviceTokenStatus.ACCESS_DENIED,
        DeviceTokenStatus.EXPIRED,
    ],
)
def test_poll_classifies_the_rfc_8628_answers(
    fake_api: FakeAPI, answer: DeviceTokenStatus
):
    fake_api.add("POST", TOKEN_PATH, status=400, json_body=oauth_error(answer))
    poll = poll_device_token(
        "dc-secret", base_api_url=BASE, transport=fake_api.transport()
    )
    assert (poll.status, poll.token) == (answer, None)
    assert form(fake_api) == {
        "grant_type": DEVICE_CODE_GRANT,
        "device_code": "dc-secret",
        "client_id": "cli",
    }


def test_poll_returns_the_login(fake_api: FakeAPI):
    fake_api.add("POST", TOKEN_PATH, json_body=LOGIN)
    poll = poll_device_token(
        "dc-secret", base_api_url=BASE, transport=fake_api.transport()
    )
    assert poll.status is DeviceTokenStatus.TOKEN
    assert poll.token is not None
    assert poll.token.model_dump(exclude_unset=True) == LOGIN


def test_poll_raises_any_other_error(fake_api: FakeAPI):
    fake_api.add(
        "POST", TOKEN_PATH, status=400, json_body=oauth_error("invalid_grant")
    )
    with pytest.raises(ValidationError) as caught:
        poll_device_token(
            "unknown", base_api_url=BASE, transport=fake_api.transport()
        )
    assert caught.value.code == "invalid_grant"


def answers(
    fake: FakeAPI, *bodies: tuple[int, Mapping[str, object]]
) -> httpx.MockTransport:
    """Pin one token-endpoint answer per poll; an extra poll is a failure."""
    queue = list(bodies)

    def handle(_request: httpx.Request) -> httpx.Response:
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    fake.add_handler("POST", TOKEN_PATH, handle)
    return fake.transport()


def assert_polled(fake: FakeAPI, times: int) -> None:
    """Each poll was the device-code grant, at the token endpoint."""
    assert len(fake.requests) == times
    for request in fake.requests:
        assert (request.method, request.path) == ("POST", TOKEN_PATH)
        assert parse_qs(request.content.decode()) == {
            "grant_type": [DEVICE_CODE_GRANT],
            "device_code": ["dc-secret"],
            "client_id": ["cli"],
        }


def test_wait_polls_until_approved(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    slept = no_sleep(monkeypatch)
    transport = answers(
        fake_api,
        (400, oauth_error("authorization_pending")),
        (400, oauth_error("slow_down")),
        (200, LOGIN),
    )
    token = wait_for_device_token(
        DeviceCode.model_validate(DEVICE),
        base_api_url=BASE,
        transport=transport,
    )
    assert token.cp_session == "cookie-value"
    assert slept == [5, 5, 10], "slow_down adds five seconds"
    assert_polled(fake_api, 3)


def test_wait_retries_a_dropped_connection(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    no_sleep(monkeypatch)

    def handle(_request: httpx.Request) -> httpx.Response:
        if len(fake_api.requests) == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json=LOGIN)

    fake_api.add_handler("POST", TOKEN_PATH, handle)
    token = wait_for_device_token(
        DeviceCode.model_validate({**DEVICE, "interval": 0}),
        base_api_url=BASE,
        transport=fake_api.transport(),
    )
    assert token.access_token == "login-access"
    assert_polled(fake_api, 2)


@pytest.mark.parametrize("answer", ["access_denied", "expired_token"])
def test_wait_ends_on_a_refusal(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch, answer: str
):
    no_sleep(monkeypatch)
    with pytest.raises(AuthenticationError) as caught:
        wait_for_device_token(
            DeviceCode.model_validate(DEVICE),
            base_api_url=BASE,
            transport=answers(fake_api, (400, oauth_error(answer))),
        )
    assert caught.value.code == answer
    assert_polled(fake_api, 1)


def test_wait_raises_any_other_error(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    no_sleep(monkeypatch)
    with pytest.raises(ValidationError) as caught:
        wait_for_device_token(
            DeviceCode.model_validate(DEVICE),
            base_api_url=BASE,
            transport=answers(fake_api, (400, oauth_error("invalid_grant"))),
        )
    assert caught.value.code == "invalid_grant"
    assert_polled(fake_api, 1)


def test_wait_gives_up_when_the_code_expires(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    no_sleep(monkeypatch)
    with pytest.raises(AuthenticationError) as caught:
        wait_for_device_token(
            DeviceCode.model_validate({**DEVICE, "expires_in": 0}),
            base_api_url=BASE,
            transport=answers(fake_api),
        )
    assert caught.value.code == "expired_token"
    assert_polled(fake_api, 0)


def test_a_login_keeps_its_fields_in_the_session(fake_api: FakeAPI):
    login = OAuthToken.model_validate({**LOGIN, "act": {"sub": "agent-1"}})
    received = datetime(2026, 10, 30, tzinfo=UTC)
    session = AuthSession.from_token(login, received_at=received)
    assert session.cp_session == "cookie-value"
    assert session.member_name == "Walk Owner"
    assert (session.cp_url, session.git_url, session.platform_url) == (
        "https://api.test",
        "https://git.test",
        "https://app.test",
    )
    assert session.act == {"sub": "agent-1"}

    restored = AuthSession.model_validate_json(session.model_dump_json())
    fake_api.add(
        "POST",
        TOKEN_PATH,
        json_body={
            "access_token": "rotated",
            "expires_in": 3600,
            "refresh_token": "rotated-refresh",
        },
    )
    refreshed = refresh_access_token(
        "login-refresh",
        DEVICE_FLOW_CLIENT_ID,
        "sess-1",
        "org-1",
        base_api_url=BASE,
        transport=fake_api.transport(),
    )
    renewed = AuthSession.from_token(
        refreshed, received_at=received, previous=restored
    )
    assert renewed.access_token == "rotated"
    assert renewed.refresh_token == "rotated-refresh"
    kept = {
        "member_name",
        "cp_session",
        "cp_url",
        "git_url",
        "platform_url",
        "act",
    }
    assert renewed.model_dump(include=kept) == session.model_dump(include=kept)


def test_development_credential_exchanges_the_login(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        json_body={"access_token": "dev", "expires_in": 900},
    )
    token = development_credential(
        "login-access", base_api_url=BASE, transport=fake_api.transport()
    )
    assert (token.access_token, token.expires_in) == ("dev", 900)
    assert form(fake_api) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": "cli",
        "subject_token": "login-access",
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
    }


def test_development_credential_refused(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        TOKEN_PATH,
        status=400,
        json_body=oauth_error("unauthorized_client"),
    )
    with pytest.raises(ValidationError) as caught:
        development_credential(
            "customer-login", base_api_url=BASE, transport=fake_api.transport()
        )
    assert caught.value.code == "unauthorized_client"


def test_oidc_logout_sends_the_cookie_and_stops_at_the_redirect(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        "/v1/oidc/logout",
        status=307,
        headers={"location": "https://idp.test/end_session"},
    )
    oidc_logout(
        "cookie-value", base_api_url=BASE, transport=fake_api.transport()
    )
    assert len(fake_api.requests) == 1, "the IdP redirect is not followed"
    request = fake_api.last_request
    assert request.headers["cookie"] == "intro_cp_session=cookie-value"
    assert "authorization" not in request.headers


def test_oidc_logout_raises_a_refusal(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/oidc/logout",
        status=403,
        json_body={"detail": "cross-site sign-out refused"},
    )
    with pytest.raises(Exception, match="cross-site"):
        oidc_logout("c", base_api_url=BASE, transport=fake_api.transport())


def test_oidc_logout_reports_a_dropped_connection(fake_api: FakeAPI):
    def handle(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    fake_api.add_handler("GET", "/v1/oidc/logout", handle)
    with pytest.raises(NetworkError):
        oidc_logout("c", base_api_url=BASE, transport=fake_api.transport())


def no_async_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(
        "introspection_sdk._async.device_code._sleep_async", record
    )
    return slept


async def test_async_wait_polls_through_a_drop_until_approved(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    slept = no_async_sleep(monkeypatch)
    queue: list[tuple[int, Mapping[str, object]] | None] = [
        (400, oauth_error("authorization_pending")),
        None,
        (400, oauth_error("slow_down")),
        (200, LOGIN),
    ]

    def handle(_request: httpx.Request) -> httpx.Response:
        answer = queue.pop(0)
        if answer is None:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(answer[0], json=answer[1])

    fake_api.add_handler("POST", TOKEN_PATH, handle)
    token = await async_wait_for_device_token(
        DeviceCode.model_validate(DEVICE),
        base_api_url=BASE,
        transport=fake_api.transport(),
    )
    assert token.cp_session == "cookie-value"
    assert slept == [5, 5, 5, 10], "slow_down adds five seconds"
    assert_polled(fake_api, 4)


@pytest.mark.parametrize("answer", ["access_denied", "expired_token"])
async def test_async_wait_ends_on_a_refusal(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch, answer: str
):
    no_async_sleep(monkeypatch)
    with pytest.raises(AuthenticationError) as caught:
        await async_wait_for_device_token(
            DeviceCode.model_validate(DEVICE),
            base_api_url=BASE,
            transport=answers(fake_api, (400, oauth_error(answer))),
        )
    assert caught.value.code == answer
    assert_polled(fake_api, 1)


async def test_async_request_device_code_sends_the_form(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/oauth/device/code", json_body=DEVICE)
    await async_request_device_code(
        project="walk",
        capabilities=["runtimes"],
        base_api_url=BASE,
        transport=fake_api.transport(),
    )
    assert form(fake_api) == {
        "client_id": "cli",
        "project": "walk",
        "capabilities": "runtimes",
    }


async def test_async_oidc_logout_reports_a_dropped_connection(
    fake_api: FakeAPI,
):
    def handle(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    fake_api.add_handler("GET", "/v1/oidc/logout", handle)
    with pytest.raises(NetworkError):
        await async_oidc_logout(
            "c", base_api_url=BASE, transport=fake_api.transport()
        )


async def test_async_device_flow_errors(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/oauth/device/code",
        status=400,
        json_body=oauth_error("invalid_scope"),
    )
    fake_api.add(
        "POST",
        TOKEN_PATH,
        status=400,
        json_body=oauth_error("invalid_grant"),
    )
    fake_api.add(
        "GET",
        "/v1/oidc/logout",
        status=403,
        json_body={"detail": "cross-site sign-out refused"},
    )
    transport = fake_api.transport()
    with pytest.raises(ValidationError) as caught:
        await async_request_device_code(
            capabilities=["nope"], base_api_url=BASE, transport=transport
        )
    assert caught.value.code == "invalid_scope"
    with pytest.raises(ValidationError) as caught:
        await async_poll_device_token(
            "unknown", base_api_url=BASE, transport=transport
        )
    assert caught.value.code == "invalid_grant"
    with pytest.raises(ValidationError) as caught:
        await async_development_credential(
            "customer-login", base_api_url=BASE, transport=transport
        )
    assert caught.value.code == "invalid_grant"
    with pytest.raises(Exception, match="cross-site"):
        await async_oidc_logout("c", base_api_url=BASE, transport=transport)


async def test_async_device_flow(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "introspection_sdk._async.device_code._sleep_async", no_wait
    )
    fake_api.add("POST", "/v1/oauth/device/code", json_body=DEVICE)
    fake_api.add("POST", TOKEN_PATH, json_body=LOGIN)
    fake_api.add("GET", "/v1/oidc/logout", status=302)
    transport = fake_api.transport()
    device = await async_request_device_code(
        base_api_url=BASE, transport=transport
    )
    poll = await async_poll_device_token(
        device.device_code.get_secret_value(),
        base_api_url=BASE,
        transport=transport,
    )
    assert poll.status is DeviceTokenStatus.TOKEN
    token = await async_wait_for_device_token(
        device, base_api_url=BASE, transport=transport
    )
    assert token.refresh_token == "login-refresh"
    await async_oidc_logout(
        token.cp_session or "", base_api_url=BASE, transport=transport
    )
    assert fake_api.last_request.path == "/v1/oidc/logout"
