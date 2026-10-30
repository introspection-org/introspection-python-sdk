"""Contract tests for the device-code login in :mod:`introspection_sdk.auth`
(CP ``POST /v1/oauth/device/code``, its token polls, the development
credential and ``GET /v1/oidc/logout``)."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from introspection_sdk import AuthenticationError, ValidationError
from introspection_sdk.auth import (
    DEVICE_CODE_GRANT,
    DeviceCode,
    DeviceTokenStatus,
    async_oidc_logout,
    async_poll_device_token,
    async_request_device_code,
    async_wait_for_device_token,
    development_credential,
    oidc_logout,
    poll_device_token,
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


def answers(*bodies: tuple[int, Mapping[str, object]]) -> httpx.MockTransport:
    queue = list(bodies)

    def handle(_request: httpx.Request) -> httpx.Response:
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def test_wait_polls_until_approved(monkeypatch: pytest.MonkeyPatch):
    slept = no_sleep(monkeypatch)
    transport = answers(
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


def test_wait_retries_a_dropped_connection(monkeypatch: pytest.MonkeyPatch):
    no_sleep(monkeypatch)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json=LOGIN)

    token = wait_for_device_token(
        DeviceCode.model_validate({**DEVICE, "interval": 0}),
        base_api_url=BASE,
        transport=httpx.MockTransport(handle),
    )
    assert token.access_token == "login-access"
    assert len(calls) == 2


@pytest.mark.parametrize("answer", ["access_denied", "expired_token"])
def test_wait_ends_on_a_refusal(monkeypatch: pytest.MonkeyPatch, answer: str):
    no_sleep(monkeypatch)
    with pytest.raises(AuthenticationError) as caught:
        wait_for_device_token(
            DeviceCode.model_validate(DEVICE),
            base_api_url=BASE,
            transport=answers((400, oauth_error(answer))),
        )
    assert caught.value.code == answer


def test_wait_gives_up_when_the_code_expires(monkeypatch: pytest.MonkeyPatch):
    no_sleep(monkeypatch)
    with pytest.raises(AuthenticationError) as caught:
        wait_for_device_token(
            DeviceCode.model_validate({**DEVICE, "expires_in": 0}),
            base_api_url=BASE,
            transport=answers(),
        )
    assert caught.value.code == "expired_token"


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
