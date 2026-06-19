"""Server-side OAuth helpers for machine and federated authentication.

These mint a short-lived, project-scoped Introspection access token from
the Control Plane ``POST /v1/oauth/token`` endpoint, so server code (CI
jobs, hosted-login backends, federation brokers) no longer hand-rolls a
form-encoded token POST:

* :func:`service_account_token` — OAuth 2.0 ``client_credentials`` grant
  for a confidential machine Application. The headless counterpart to a
  long-lived API key: the ``client_id`` / ``client_secret`` stay
  server-side and you re-mint when the token expires (no refresh token
  is issued).
* :func:`token_exchange` — RFC 8693 token-exchange: trade an end user's
  partner-IdP token for a project-scoped access token for a federated
  ``customer`` member.
* :func:`authorization_code_token` — RFC 6749 / PKCE ``authorization_code``
  exchange for the hosted-login callback.

Every helper returns the shared :class:`OAuthToken` shape, which carries
``dp_url`` — the Data Plane endpoint the CP resolved for the token's
project. A broker hands that straight to a browser SDK as ``dpUrl`` so
the SPA connects without separately configured Data Plane URLs.

Each function has an ``async_`` twin (:func:`async_service_account_token`
etc.) for use from :class:`~introspection_sdk.AsyncIntrospectionClient`
and other ``asyncio`` callers. The minted ``access_token`` is an ordinary
CP bearer token, so it drops straight into
:class:`~introspection_sdk.IntrospectionClient`, or use
:meth:`IntrospectionClient.from_service_account` to mint and construct in
one call.
"""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, ConfigDict

from introspection_sdk._errors import NetworkError, error_from_response

__all__ = [
    "OAuthToken",
    "async_authorization_code_token",
    "async_service_account_token",
    "async_token_exchange",
    "authorization_code_token",
    "service_account_token",
    "token_exchange",
]

_DEFAULT_BASE_API_URL = "https://api.introspection.dev"
_TOKEN_PATH = "/v1/oauth/token"
_GRANT_CLIENT_CREDENTIALS = "client_credentials"
_GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
_GRANT_AUTHORIZATION_CODE = "authorization_code"
_SUBJECT_TOKEN_TYPE_ID_TOKEN = "urn:ietf:params:oauth:token-type:id_token"


class OAuthToken(BaseModel):
    """CP ``POST /v1/oauth/token`` response.

    No refresh token is issued for the machine grants — re-mint (call the
    helper again) once it expires. Additional wire fields the CP returns
    (``project_id``, ``org_id``, …) are preserved but left unmodelled.
    """

    model_config = ConfigDict(extra="allow")

    #: Project-scoped RS256 access token (``Authorization: Bearer …``).
    access_token: str
    #: Always ``"Bearer"``.
    token_type: str = "Bearer"
    #: Token lifetime in seconds.
    expires_in: int
    #: The granted (scope-capped) scope, when the CP returns one.
    scope: str | None = None
    #: Data Plane API base URL for the token's project, resolved by the
    #: CP. ``None`` when no deployment resolves; the caller then needs an
    #: explicit DP URL. Hand this to the browser SDK as ``dpUrl``.
    dp_url: str | None = None


def _resolve_base_api_url(base_api_url: str | None) -> str:
    resolved = base_api_url or os.getenv(
        "INTROSPECTION_BASE_API_URL", _DEFAULT_BASE_API_URL
    )
    return resolved.rstrip("/")


def _service_account_form(
    client_id: str,
    client_secret: str,
    project_id: str,
    scope: str | None,
) -> dict[str, str]:
    form = {
        "grant_type": _GRANT_CLIENT_CREDENTIALS,
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": project_id,
    }
    if scope:
        form["scope"] = scope
    return form


def _token_exchange_form(
    subject_token: str,
    client_id: str,
    project_id: str,
    subject_token_type: str | None,
    scope: str | None,
) -> dict[str, str]:
    form = {
        "grant_type": _GRANT_TOKEN_EXCHANGE,
        "subject_token": subject_token,
        "subject_token_type": subject_token_type
        or _SUBJECT_TOKEN_TYPE_ID_TOKEN,
        "client_id": client_id,
        "project_id": project_id,
    }
    if scope:
        form["scope"] = scope
    return form


def _authorization_code_form(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, str]:
    return {
        "grant_type": _GRANT_AUTHORIZATION_CODE,
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }


def _post_token_form(
    base_api_url: str,
    form: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    try:
        with httpx.Client(
            base_url=base_api_url, timeout=30.0, transport=transport
        ) as client:
            res = client.post(_TOKEN_PATH, data=form)
    except httpx.HTTPError as exc:
        raise NetworkError(str(exc)) from exc
    if res.status_code >= 400:
        raise error_from_response(res)
    return OAuthToken.model_validate(res.json())


async def _apost_token_form(
    base_api_url: str,
    form: dict[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    try:
        async with httpx.AsyncClient(
            base_url=base_api_url, timeout=30.0, transport=transport
        ) as client:
            res = await client.post(_TOKEN_PATH, data=form)
    except httpx.HTTPError as exc:
        raise NetworkError(str(exc)) from exc
    if res.status_code >= 400:
        raise error_from_response(res)
    return OAuthToken.model_validate(res.json())


# --- client_credentials (service account) ---------------------------


def service_account_token(
    client_id: str,
    client_secret: str,
    project_id: str,
    *,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """Mint a project-scoped CP access token from service-account creds.

    ``client_id`` (``intro_app_…``) and ``client_secret`` (``intro_sk_…``)
    come from a confidential machine Application; ``project_id`` scopes the
    token (the project must belong to the Application's organization).
    ``scope`` is capped server-side to the Application's allowed scopes.

    See :func:`async_service_account_token` for the ``asyncio`` twin and
    :meth:`IntrospectionClient.from_service_account` to mint and construct
    a client in one call.
    """
    form = _service_account_form(
        client_id=client_id,
        client_secret=client_secret,
        project_id=project_id,
        scope=scope,
    )
    return _post_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_service_account_token(
    client_id: str,
    client_secret: str,
    project_id: str,
    *,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`service_account_token`."""
    form = _service_account_form(
        client_id=client_id,
        client_secret=client_secret,
        project_id=project_id,
        scope=scope,
    )
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


# --- token-exchange (RFC 8693, federated identity) ------------------


def token_exchange(
    subject_token: str,
    client_id: str,
    project_id: str,
    *,
    subject_token_type: str | None = None,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """RFC 8693 token-exchange against CP ``POST /v1/oauth/token``.

    Trade an end user's partner-IdP token (``subject_token``, an
    ``id_token`` by default) for a project-scoped access token for a
    federated ``customer`` member. ``client_id`` is the federated
    (public) Application's id. Run this server-side in a broker — the
    subject token should not be re-handled in the browser.
    """
    form = _token_exchange_form(
        subject_token=subject_token,
        client_id=client_id,
        project_id=project_id,
        subject_token_type=subject_token_type,
        scope=scope,
    )
    return _post_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_token_exchange(
    subject_token: str,
    client_id: str,
    project_id: str,
    *,
    subject_token_type: str | None = None,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`token_exchange`."""
    form = _token_exchange_form(
        subject_token=subject_token,
        client_id=client_id,
        project_id=project_id,
        subject_token_type=subject_token_type,
        scope=scope,
    )
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


# --- authorization_code (PKCE, hosted login) ------------------------


def authorization_code_token(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """RFC 6749 / PKCE ``authorization_code`` exchange.

    Run this in your backend so the hosted-login callback does not
    hand-roll the token POST. ``client_id`` is the public SPA
    Application; ``code_verifier`` pairs with the authorize-step
    challenge; ``redirect_uri`` must match the authorize call.
    """
    form = _authorization_code_form(
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    return _post_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_authorization_code_token(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`authorization_code_token`."""
    form = _authorization_code_form(
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )
