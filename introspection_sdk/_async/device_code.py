"""Re-exported by :mod:`introspection_sdk.auth`: the RFC 8628 device-code
login ``introspection login`` runs, its development credential, and the
OIDC sign-out that ends it."""

from __future__ import annotations

import logging
import time

import httpx2 as httpx

from introspection_sdk._async.auth import (
    _GRANT_TOKEN_EXCHANGE,
    _cp_post_async,
    _post_token_form_async,
)
from introspection_sdk._auth_common import OAuthToken, _resolve_base_api_url
from introspection_sdk._backoff import _sleep_async
from introspection_sdk._device_code_common import (
    DEVICE_CODE_GRANT,
    DEVICE_FLOW_CLIENT_ID,
    MAX_EXPIRES_IN_SECONDS,
    MAX_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    SLOW_DOWN_SECONDS,
    DeviceCode,
    DeviceTokenPoll,
    DeviceTokenStatus,
)
from introspection_sdk._errors import (
    AuthenticationError,
    IntrospectionAPIError,
    NetworkError,
    error_from_response,
)

logger = logging.getLogger(__name__)

DEVICE_CODE_PATH = "/v1/oauth/device/code"
OIDC_LOGOUT_PATH = "/v1/oidc/logout"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
POLL_ANSWERS = {
    DeviceTokenStatus.PENDING,
    DeviceTokenStatus.SLOW_DOWN,
    DeviceTokenStatus.ACCESS_DENIED,
    DeviceTokenStatus.EXPIRED,
}


async def async_request_device_code(
    *,
    client_id: str = DEVICE_FLOW_CLIENT_ID,
    project: str | None = None,
    capabilities: list[str] | None = None,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DeviceCode:
    """Start a device-code login (CP ``POST /v1/oauth/device/code``).

    ``project`` (slug or id) preselects the project on the activation page;
    the member still picks it when approving. ``capabilities`` names the
    bundles to limit the login to: the Control Plane intersects them with
    the member's entitlement, so they only narrow it, and an unknown one is
    a ``ValidationError``.
    """
    form = {"client_id": client_id}
    if project:
        form["project"] = project
    if capabilities:
        form["capabilities"] = ",".join(capabilities)
    res = await _cp_post_async(
        _resolve_base_api_url(base_api_url),
        DEVICE_CODE_PATH,
        data=form,
        transport=transport,
    )
    logger.debug("device code requested", extra={"client_id": client_id})
    return DeviceCode.model_validate(res.json())


async def async_poll_device_token(
    device_code: str,
    *,
    client_id: str = DEVICE_FLOW_CLIENT_ID,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DeviceTokenPoll:
    """Poll the token endpoint once with the device-code grant.

    The four RFC 8628 answers come back as a :class:`DeviceTokenPoll`; any
    other error (an unknown ``device_code`` is ``invalid_grant``) raises.
    """
    form = {
        "grant_type": DEVICE_CODE_GRANT,
        "device_code": device_code,
        "client_id": client_id,
    }
    try:
        token = await _post_token_form_async(
            _resolve_base_api_url(base_api_url), form, transport=transport
        )
    except IntrospectionAPIError as exc:
        if exc.status_code == 400 and exc.code in POLL_ANSWERS:
            return DeviceTokenPoll(status=DeviceTokenStatus(exc.code))
        raise
    return DeviceTokenPoll(status=DeviceTokenStatus.TOKEN, token=token)


async def async_wait_for_device_token(
    device: DeviceCode,
    *,
    client_id: str = DEVICE_FLOW_CLIENT_ID,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Poll until the member approves ``device`` and return the login.

    Waits ``device.interval`` between polls (bounded to 1-60 seconds) and
    five seconds longer after each ``slow_down``. A dropped connection is
    retried on the next poll. Raises :class:`AuthenticationError` with
    ``code="expired_token"`` when the code runs out, and with
    ``code="access_denied"`` when the member refuses it.

    The returned token carries ``cp_session`` for Control Plane routes,
    ``refresh_token`` / ``session_id`` / ``org_id`` for
    :func:`refresh_access_token`, and the URLs the login resolved.
    """
    interval = min(
        max(device.interval, MIN_INTERVAL_SECONDS), MAX_INTERVAL_SECONDS
    )
    deadline = time.monotonic() + min(
        device.expires_in, MAX_EXPIRES_IN_SECONDS
    )
    code = device.device_code.get_secret_value()
    while True:
        await _sleep_async(interval)
        if time.monotonic() >= deadline:
            break
        try:
            poll = await async_poll_device_token(
                code,
                client_id=client_id,
                base_api_url=base_api_url,
                transport=transport,
            )
        except NetworkError:
            logger.debug("device token poll failed; polling again")
            continue
        if poll.token is not None:
            return poll.token
        if poll.status is DeviceTokenStatus.SLOW_DOWN:
            interval = min(interval + SLOW_DOWN_SECONDS, MAX_INTERVAL_SECONDS)
        elif poll.status is DeviceTokenStatus.ACCESS_DENIED:
            raise AuthenticationError(
                "The login was denied in the browser",
                status_code=400,
                code=DeviceTokenStatus.ACCESS_DENIED,
            )
        elif poll.status is DeviceTokenStatus.EXPIRED:
            break
    raise AuthenticationError(
        "The device code expired before the login was approved",
        status_code=400,
        code=DeviceTokenStatus.EXPIRED,
    )


async def async_development_credential(
    access_token: str,
    *,
    client_id: str = DEVICE_FLOW_CLIENT_ID,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Trade a login's access token for the short-lived development
    credential ``introspection dev`` attaches with (RFC 8693
    token-exchange at CP ``POST /v1/oauth/token``).

    Only a business member's project-scoped login holding
    ``runtimes:write`` qualifies; any other is a ``ValidationError``
    (``unauthorized_client``, ``invalid_target`` or ``invalid_grant``).
    Mint a new one when it expires.
    """
    form = {
        "grant_type": _GRANT_TOKEN_EXCHANGE,
        "client_id": client_id,
        "subject_token": access_token,
        "subject_token_type": ACCESS_TOKEN_TYPE,
    }
    return await _post_token_form_async(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_oidc_logout(
    cp_session: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """End the Control Plane session behind a ``cp_session`` cookie, and
    with it the session's Data Plane tokens (CP ``GET /v1/oidc/logout``).

    The first answer has already revoked the session; its redirect starts a
    browser's sign-out at the identity provider, which a headless client
    has no use for, so it is not followed. A cookie that names no live
    session revokes nothing and answers the same way.
    """
    try:
        async with httpx.AsyncClient(
            base_url=_resolve_base_api_url(base_api_url),
            timeout=30.0,
            transport=transport,
            follow_redirects=False,
        ) as client:
            res = await client.get(
                OIDC_LOGOUT_PATH,
                headers={"Cookie": f"intro_cp_session={cp_session}"},
            )
    except httpx.HTTPError as exc:
        raise NetworkError(str(exc)) from exc
    if res.status_code >= 400:
        raise error_from_response(res)
    logger.debug("signed out", extra={"status": res.status_code})


__all__ = [
    "async_development_credential",
    "async_oidc_logout",
    "async_poll_device_token",
    "async_request_device_code",
    "async_wait_for_device_token",
]
