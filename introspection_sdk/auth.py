"""OAuth helpers for every Application type, plus native email-code sign-in.

These mint a short-lived, project-scoped Introspection access token from
the Control Plane ``POST /v1/oauth/token`` endpoint, so callers no longer
hand-roll a form-encoded token POST. An Application has exactly one type,
and each type has one way in:

* ``service_account`` — :func:`service_account_token`, the OAuth 2.0
  ``client_credentials`` grant for a confidential machine client. The
  headless counterpart to a long-lived API key: the ``client_id`` /
  ``client_secret`` stay server-side and you re-mint when the token
  expires (no refresh token is issued).
* ``jwks`` — :func:`token_exchange`, RFC 8693 token-exchange: trade an end
  user's JWT from your own identity provider for a project-scoped access
  token for a federated ``customer`` member. No refresh token is issued;
  exchange again before it expires.
* ``spa`` — :func:`authorization_code_token`, the RFC 6749 / PKCE
  ``authorization_code`` exchange for the hosted-login callback. An ``spa``
  with a brokered identity provider also exchanges that login's
  ``id_token`` through :func:`token_exchange`.
* ``native`` — email-code sign-in for a ``customer`` member:
  :class:`EmailCodeAuth` / :class:`AsyncEmailCodeAuth` send the code,
  verify it, and keep the refreshable session current. The one-shot
  calls underneath are :func:`send_email_code`, :func:`email_code_token`,
  :func:`refresh_access_token` and :func:`revoke_session`.

A token issued to an end user (``jwks``, ``spa``, ``native``) carries at
most the Application's ``allowed_scopes``.

Every token helper returns the shared :class:`OAuthToken` shape, which
carries ``dp_url`` — the Data Plane endpoint the CP resolved for the
token's project — so a client needs no separately configured Data Plane
URL.

Each function has an ``async_`` twin (:func:`async_service_account_token`
etc.) for use from :class:`~introspection_sdk.AsyncIntrospectionClient`
and other ``asyncio`` callers. A ``service_account`` token is an ordinary
CP bearer token, so it drops straight into
:class:`~introspection_sdk.IntrospectionClient`, or use
:meth:`IntrospectionClient.from_service_account` to mint and construct in
one call. A ``native`` email-code token is a Data Plane credential:
Control Plane routes reject it.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict

from introspection_sdk._errors import (
    AuthenticationError,
    IntrospectionAPIError,
    NetworkError,
    ValidationError,
    error_from_response,
)

if TYPE_CHECKING:
    from introspection_sdk.client import (
        AsyncIntrospectionClient,
        IntrospectionClient,
    )

__all__ = [
    "GRANT_EMAIL_CODE",
    "AsyncCredentialProvider",
    "AsyncEmailCodeAuth",
    "AuthSession",
    "CredentialProvider",
    "EmailCodeAuth",
    "OAuthToken",
    "SignInSupersededError",
    "async_authorization_code_token",
    "async_email_code_token",
    "async_refresh_access_token",
    "async_revoke_session",
    "async_send_email_code",
    "async_service_account_token",
    "async_token_exchange",
    "authorization_code_token",
    "email_code_token",
    "refresh_access_token",
    "revoke_session",
    "send_email_code",
    "service_account_token",
    "token_exchange",
]

_DEFAULT_BASE_API_URL = "https://api.introspection.dev"
_TOKEN_PATH = "/v1/oauth/token"
_GRANT_CLIENT_CREDENTIALS = "client_credentials"
_GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
_GRANT_AUTHORIZATION_CODE = "authorization_code"
_GRANT_REFRESH_TOKEN = "refresh_token"
_SUBJECT_TOKEN_TYPE_ID_TOKEN = "urn:ietf:params:oauth:token-type:id_token"
_EMAIL_CODE_PATH = "/v1/oauth/email/code"
_REVOKE_PATH = "/v1/oauth/revoke"
#: ``grant_type`` of native email-code sign-in at ``POST /v1/oauth/token``.
GRANT_EMAIL_CODE = "urn:introspection:params:oauth:grant-type:email_code"


class OAuthToken(BaseModel):
    """CP ``POST /v1/oauth/token`` response.

    The machine and federated grants issue no refresh token — re-mint (call
    the helper again) once it expires. ``email_code`` and ``refresh_token``
    return the refresh token plus the ``session_id`` / ``org_id`` that key the
    next refresh. Additional wire fields are preserved but left unmodelled.
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
    #: explicit DP URL. Hand this to a browser client so it needs no
    #: separate Data Plane configuration.
    dp_url: str | None = None
    #: Rotating refresh token; set only by the session-backed grants.
    refresh_token: str | None = None
    #: The CP session row (the access token's ``jti``).
    session_id: str | None = None
    org_id: str | None = None
    project_id: str | None = None
    member_id: str | None = None


def _resolve_base_api_url(base_api_url: str | None) -> str:
    resolved = base_api_url or os.getenv(
        "INTROSPECTION_BASE_API_URL", _DEFAULT_BASE_API_URL
    )
    return resolved.rstrip("/")


def _service_account_form(
    client_id: str,
    client_secret: str,
    project: str,
    scope: str | None,
) -> dict[str, str]:
    form = {
        "grant_type": _GRANT_CLIENT_CREDENTIALS,
        "client_id": client_id,
        "client_secret": client_secret,
        "project": project,
    }
    if scope:
        form["scope"] = scope
    return form


def _token_exchange_form(
    subject_token: str,
    client_id: str,
    project: str,
    subject_token_type: str | None,
    scope: str | None,
) -> dict[str, str]:
    form = {
        "grant_type": _GRANT_TOKEN_EXCHANGE,
        "subject_token": subject_token,
        "subject_token_type": subject_token_type
        or _SUBJECT_TOKEN_TYPE_ID_TOKEN,
        "client_id": client_id,
        "project": project,
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


def _cp_post(
    base_api_url: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    json: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    try:
        with httpx.Client(
            base_url=base_api_url, timeout=30.0, transport=transport
        ) as client:
            res = client.post(path, data=data, json=json)
    except httpx.HTTPError as exc:
        raise NetworkError(str(exc)) from exc
    if res.status_code >= 400:
        raise error_from_response(res)
    return res


async def _acp_post(
    base_api_url: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    json: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(
            base_url=base_api_url, timeout=30.0, transport=transport
        ) as client:
            res = await client.post(path, data=data, json=json)
    except httpx.HTTPError as exc:
        raise NetworkError(str(exc)) from exc
    if res.status_code >= 400:
        raise error_from_response(res)
    return res


def _post_token_form(
    base_api_url: str,
    form: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    res = _cp_post(base_api_url, _TOKEN_PATH, data=form, transport=transport)
    return OAuthToken.model_validate(res.json())


async def _apost_token_form(
    base_api_url: str,
    form: dict[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    res = await _acp_post(
        base_api_url, _TOKEN_PATH, data=form, transport=transport
    )
    return OAuthToken.model_validate(res.json())


# --- client_credentials (service account) ---------------------------


def service_account_token(
    client_id: str,
    client_secret: str,
    project: str,
    *,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """Mint a project-scoped CP access token from service-account creds.

    ``client_id`` (``intro_app_…``) and ``client_secret`` (``intro_sk_…``)
    come from a ``service_account`` Application; ``project`` scopes the
    token (the project must belong to the Application's organization).
    ``scope`` is capped server-side to the Application's allowed scopes.

    See :func:`async_service_account_token` for the ``asyncio`` twin and
    :meth:`IntrospectionClient.from_service_account` to mint and construct
    a client in one call.
    """
    form = _service_account_form(
        client_id=client_id,
        client_secret=client_secret,
        project=project,
        scope=scope,
    )
    return _post_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_service_account_token(
    client_id: str,
    client_secret: str,
    project: str,
    *,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`service_account_token`."""
    form = _service_account_form(
        client_id=client_id,
        client_secret=client_secret,
        project=project,
        scope=scope,
    )
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


# --- token-exchange (RFC 8693, federated identity) ------------------


def token_exchange(
    subject_token: str,
    client_id: str,
    project: str,
    *,
    subject_token_type: str | None = None,
    scope: str | None = None,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """RFC 8693 token-exchange against CP ``POST /v1/oauth/token``.

    Trade an end user's identity-provider JWT (``subject_token``) for a
    project-scoped access token for a federated ``customer`` member.
    ``client_id`` is a ``jwks`` Application's id (or a brokered ``spa``'s,
    with the brokered login's ``id_token``). The server accepts only the
    ``id_token`` subject type, whatever kind of JWT the provider issued,
    so leave ``subject_token_type`` at its default. The granted scope is
    capped to the Application's ``allowed_scopes``; no refresh token is
    issued, so exchange again before ``expires_in`` lapses.
    """
    form = _token_exchange_form(
        subject_token=subject_token,
        client_id=client_id,
        project=project,
        subject_token_type=subject_token_type,
        scope=scope,
    )
    return _post_token_form(
        _resolve_base_api_url(base_api_url), form, transport=transport
    )


async def async_token_exchange(
    subject_token: str,
    client_id: str,
    project: str,
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
        project=project,
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
    hand-roll the token POST. ``client_id`` is the ``spa``
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


# --- email_code (native sign-in) ------------------------------------


def _email_code_form(
    email: str, code: str, client_id: str, project: str
) -> dict[str, str]:
    # The code is opaque: a returning user's is 6 digits, a new user's first
    # one is 6 characters of A-Z0-9, so it is never checked for shape here.
    return {
        "grant_type": GRANT_EMAIL_CODE,
        "client_id": client_id,
        "email": email,
        "code": code.strip(),
        "project": project,
    }


def _refresh_form(
    refresh_token: str, client_id: str, session_id: str, org_id: str
) -> dict[str, str]:
    return {
        "grant_type": _GRANT_REFRESH_TOKEN,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "session_id": session_id,
        "org_id": org_id,
    }


def send_email_code(
    email: str,
    client_id: str,
    project: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Email a sign-in code to ``email`` (CP ``POST /v1/oauth/email/code``).

    ``client_id`` is a ``native`` Application's id and ``project`` the
    project slug or id the session will be scoped to. The answer is the same
    whether or not the email has an account. A rate-limited send raises
    :class:`~introspection_sdk.RateLimitError` carrying ``retry_after``.
    """
    _cp_post(
        _resolve_base_api_url(base_api_url),
        _EMAIL_CODE_PATH,
        json={"client_id": client_id, "email": email, "project": project},
        transport=transport,
    )


async def async_send_email_code(
    email: str,
    client_id: str,
    project: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Async twin of :func:`send_email_code`."""
    await _acp_post(
        _resolve_base_api_url(base_api_url),
        _EMAIL_CODE_PATH,
        json={"client_id": client_id, "email": email, "project": project},
        transport=transport,
    )


def email_code_token(
    email: str,
    code: str,
    client_id: str,
    project: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """Exchange an emailed code for a refreshable ``customer`` session.

    Accepts letters as well as digits. A wrong, expired or reused code raises
    :class:`~introspection_sdk.ValidationError` with ``code="invalid_grant"``.
    The returned token carries ``refresh_token``, ``session_id`` and
    ``org_id`` for :func:`refresh_access_token`, and ``dp_url``.
    """
    return _post_token_form(
        _resolve_base_api_url(base_api_url),
        _email_code_form(email, code, client_id, project),
        transport=transport,
    )


async def async_email_code_token(
    email: str,
    code: str,
    client_id: str,
    project: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`email_code_token`."""
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url),
        _email_code_form(email, code, client_id, project),
        transport=transport,
    )


def refresh_access_token(
    refresh_token: str,
    client_id: str,
    session_id: str,
    org_id: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OAuthToken:
    """Renew a session-backed token with the ``refresh_token`` grant.

    The refresh token rotates: persist the returned one. The response
    carries no ``dp_url``; keep the one from sign-in.
    """
    return _post_token_form(
        _resolve_base_api_url(base_api_url),
        _refresh_form(refresh_token, client_id, session_id, org_id),
        transport=transport,
    )


async def async_refresh_access_token(
    refresh_token: str,
    client_id: str,
    session_id: str,
    org_id: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthToken:
    """Async twin of :func:`refresh_access_token`."""
    return await _apost_token_form(
        _resolve_base_api_url(base_api_url),
        _refresh_form(refresh_token, client_id, session_id, org_id),
        transport=transport,
    )


def revoke_session(
    session_id: str,
    org_id: str,
    client_id: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Revoke a session (CP ``POST /v1/oauth/revoke``); its next refresh fails."""
    _cp_post(
        _resolve_base_api_url(base_api_url),
        _REVOKE_PATH,
        data={
            "client_id": client_id,
            "session_id": session_id,
            "org_id": org_id,
        },
        transport=transport,
    )


async def async_revoke_session(
    session_id: str,
    org_id: str,
    client_id: str,
    *,
    base_api_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Async twin of :func:`revoke_session`."""
    await _acp_post(
        _resolve_base_api_url(base_api_url),
        _REVOKE_PATH,
        data={
            "client_id": client_id,
            "session_id": session_id,
            "org_id": org_id,
        },
        transport=transport,
    )


# --- native session ---------------------------------------------------


def _jwt_claims(token: str) -> dict[str, Any]:
    """The payload of a JWT, decoded WITHOUT verifying it; ``{}`` if not one."""
    segments = token.split(".")
    if len(segments) < 2:
        return {}
    padded = segments[1] + "=" * (-len(segments[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        return {}
    return claims if isinstance(claims, dict) else {}


def _claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    return value if isinstance(value, str) else None


class AuthSession(BaseModel):
    """A signed-in member's session: the access token plus what renews it.

    Serializable (``model_dump_json`` / ``model_validate_json``) so an app can
    keep it between runs and hand it back as ``EmailCodeAuth(session=...)``.
    Treat it as a secret: it holds the refresh token.
    """

    model_config = ConfigDict(extra="allow")

    access_token: str
    expires_at: datetime | None = None
    #: Rotated by every refresh.
    refresh_token: str | None = None
    #: The CP session row (the access token's ``jti``).
    session_id: str | None = None
    org_id: str | None = None
    project_id: str | None = None
    member_id: str | None = None
    #: The Data Plane URL returned at sign-in.
    dp_url: str | None = None
    scope: str | None = None

    @classmethod
    def from_token(
        cls,
        token: OAuthToken,
        *,
        received_at: datetime,
        previous: AuthSession | None = None,
    ) -> AuthSession:
        """From a token response; missing ids come from the JWT, then ``previous``."""
        claims = _jwt_claims(token.access_token)
        return cls(
            access_token=token.access_token,
            expires_at=received_at + timedelta(seconds=token.expires_in),
            refresh_token=token.refresh_token
            or (previous.refresh_token if previous else None),
            session_id=token.session_id
            or _claim(claims, "jti")
            or (previous.session_id if previous else None),
            org_id=token.org_id
            or _claim(claims, "org_id")
            or (previous.org_id if previous else None),
            project_id=token.project_id
            or _claim(claims, "project_id")
            or (previous.project_id if previous else None),
            member_id=token.member_id
            or _claim(claims, "member_id")
            or (previous.member_id if previous else None),
            dp_url=token.dp_url or (previous.dp_url if previous else None),
            scope=token.scope or (previous.scope if previous else None),
        )


class SignInSupersededError(Exception):
    """A sign-in or refresh response arrived after a newer sign-in or a
    sign-out, so it was discarded rather than overwrite the newer state."""


class CredentialProvider(Protocol):
    """Supplies ``Authorization`` to a client and renews it after a ``401``.

    :class:`EmailCodeAuth` implements it; pass one as
    ``IntrospectionClient(credentials=...)``.
    """

    def authorization(self) -> str | None:
        """The header value to send, or ``None`` to send none."""
        ...

    def refresh_after_unauthorized(self, rejected: str | None) -> bool:
        """Called after a ``401`` for a request sent with ``rejected``;
        return ``True`` to retry it once with :meth:`authorization`."""
        ...


class AsyncCredentialProvider(Protocol):
    """Async twin of :class:`CredentialProvider`."""

    async def authorization(self) -> str | None: ...

    async def refresh_after_unauthorized(
        self, rejected: str | None
    ) -> bool: ...


def _is_rejection(error: IntrospectionAPIError) -> bool:
    """The server refused the session, as opposed to a failure worth retrying."""
    return (
        isinstance(error, AuthenticationError | ValidationError)
        or error.status_code == 403
        or error.code == "invalid_grant"
    )


def _rejected(error: IntrospectionAPIError) -> AuthenticationError:
    return AuthenticationError(
        f"The session is no longer valid: {error}",
        status_code=error.status_code,
        code=error.code,
        request_id=error.request_id,
        body=error.body,
    )


def _not_signed_in() -> AuthenticationError:
    return AuthenticationError("Not signed in", status_code=0)


def _utcnow() -> datetime:
    return datetime.now(UTC)


SessionListener = Callable[["AuthSession | None"], None]


class _EmailCodeAuthBase:
    def __init__(
        self,
        client_id: str,
        project: str,
        *,
        session: AuthSession | None = None,
        base_api_url: str | None = None,
        leeway: float = 60.0,
        on_session_change: SessionListener | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.client_id = client_id
        self.project = project
        self.base_api_url = _resolve_base_api_url(base_api_url)
        self.leeway = leeway
        self._session = session
        self._generation = 0
        self._on_session_change = on_session_change
        self._clock = clock

    @property
    def current_session(self) -> AuthSession | None:
        """The session as held, without refreshing it."""
        return self._session

    def _expiring(self, session: AuthSession) -> bool:
        return (
            session.expires_at is not None
            and session.expires_at - timedelta(seconds=self.leeway)
            <= self._clock()
        )

    def _refresh_key(self, session: AuthSession) -> tuple[str, str, str]:
        if not (
            session.refresh_token and session.session_id and session.org_id
        ):
            raise AuthenticationError(
                "The session has no refresh token", status_code=0
            )
        return session.refresh_token, session.session_id, session.org_id

    def _adopt(self, token: OAuthToken, expected: int | None) -> AuthSession:
        """Install a sign-in response unless a newer one superseded it."""
        if expected is not None and self._generation != expected:
            raise SignInSupersededError(
                "A sign-out or another sign-in completed first"
            )
        self._generation += 1
        self._session = AuthSession.from_token(
            token, received_at=self._clock()
        )
        self._notify(self._session)
        return self._session

    def _replace(
        self, previous: AuthSession, token: OAuthToken, generation: int
    ) -> AuthSession:
        if self._generation != generation:
            raise SignInSupersededError(
                "A sign-out or sign-in completed during the refresh"
            )
        self._session = AuthSession.from_token(
            token, received_at=self._clock(), previous=previous
        )
        self._notify(self._session)
        return self._session

    def _clear(self) -> AuthSession | None:
        previous = self._session
        self._generation += 1
        self._session = None
        if previous is not None:
            self._notify(None)
        return previous

    def _notify(self, session: AuthSession | None) -> None:
        if self._on_session_change is not None:
            self._on_session_change(session)


class EmailCodeAuth(_EmailCodeAuthBase):
    """Native email-code sign-in for a ``native`` Application's end users.

    Send a code, verify it, and use the session: the access token is renewed
    ``leeway`` seconds before it expires and after a ``401``, with concurrent
    callers sharing one refresh. A sign-in or refresh response that arrives
    after a newer sign-in or a sign-out is dropped and raises
    :class:`SignInSupersededError`::

        auth = EmailCodeAuth(client_id="intro_app_…", project="ark")
        auth.send_code("user@example.com")
        auth.verify_code("user@example.com", input("Code: "))
        client = auth.client()

    Pass ``session=`` to restore a session kept from an earlier run and
    ``on_session_change`` to persist every change (``None`` on sign-out).
    The token is a Data Plane credential for a ``customer`` member scoped to
    the Application's ``allowed_scopes``: Control Plane routes reject it.
    """

    def __init__(
        self,
        client_id: str,
        project: str,
        *,
        session: AuthSession | None = None,
        base_api_url: str | None = None,
        leeway: float = 60.0,
        on_session_change: SessionListener | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        super().__init__(
            client_id,
            project,
            session=session,
            base_api_url=base_api_url,
            leeway=leeway,
            on_session_change=on_session_change,
            clock=clock,
        )
        self.transport = transport
        self._state = threading.RLock()
        self._refreshing = threading.Lock()

    def send_code(self, email: str) -> None:
        """Email a one-time code to ``email``."""
        send_email_code(
            email,
            self.client_id,
            self.project,
            base_api_url=self.base_api_url,
            transport=self.transport,
        )

    def verify_code(self, email: str, code: str) -> AuthSession:
        """Verify the code sent to ``email`` and sign in."""
        with self._state:
            generation = self._generation
        token = email_code_token(
            email,
            code,
            self.client_id,
            self.project,
            base_api_url=self.base_api_url,
            transport=self.transport,
        )
        with self._state:
            return self._adopt(token, generation)

    def set_session(self, token: OAuthToken | AuthSession) -> AuthSession:
        """Adopt a session obtained elsewhere."""
        with self._state:
            if isinstance(token, OAuthToken):
                return self._adopt(token, None)
            self._generation += 1
            self._session = token
            self._notify(token)
            return token

    def get_session(self) -> AuthSession | None:
        """The current session, refreshed first when within ``leeway`` of
        expiry; ``None`` when signed out."""
        session = self._session
        if session is None:
            return None
        if self._expiring(session):
            return self.refresh()
        return session

    def refresh(self) -> AuthSession:
        """Renew the session now, or wait for the renewal in flight. A
        refresh the server rejects signs out and raises
        :class:`~introspection_sdk.AuthenticationError`."""
        with self._state:
            session, generation = self._session, self._generation
        if session is None:
            raise _not_signed_in()
        with self._refreshing:
            with self._state:
                if self._generation != generation:
                    raise SignInSupersededError(
                        "A sign-out or sign-in completed during the refresh"
                    )
                if self._session is not session and self._session is not None:
                    return self._session
            refresh_token, session_id, org_id = self._refresh_key(session)
            try:
                token = refresh_access_token(
                    refresh_token,
                    self.client_id,
                    session_id,
                    org_id,
                    base_api_url=self.base_api_url,
                    transport=self.transport,
                )
            except IntrospectionAPIError as exc:
                if not _is_rejection(exc):
                    raise
                with self._state:
                    if self._generation != generation:
                        raise SignInSupersededError(
                            "A sign-out or sign-in completed during the refresh"
                        ) from exc
                    self._clear()
                raise _rejected(exc) from exc
            with self._state:
                return self._replace(session, token, generation)

    def sign_out(self) -> None:
        """Forget the session, then revoke it on the Control Plane. The local
        session is cleared even when revocation fails."""
        with self._state:
            session = self._clear()
        if session is None or session.refresh_token is None:
            return
        if session.session_id and session.org_id:
            revoke_session(
                session.session_id,
                session.org_id,
                self.client_id,
                base_api_url=self.base_api_url,
                transport=self.transport,
            )

    def authorization(self) -> str | None:
        session = self.get_session()
        return f"Bearer {session.access_token}" if session else None

    def refresh_after_unauthorized(self, rejected: str | None) -> bool:
        session = self.get_session()
        if session is None:
            return False
        if (
            rejected is not None
            and rejected != f"Bearer {session.access_token}"
        ):
            return True
        self.refresh()
        return True

    def client(
        self,
        *,
        dp_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> IntrospectionClient:
        """A client authenticated as the signed-in member, pointed at the
        session's ``dp_url`` unless ``dp_url`` overrides it. Only its Data
        Plane namespaces accept the token."""
        # Imported here: the client module imports this one.
        from introspection_sdk.client import IntrospectionClient

        session = self.get_session()
        if session is None:
            raise _not_signed_in()
        return IntrospectionClient(
            credentials=self,
            base_api_url=self.base_api_url,
            dp_url=dp_url or session.dp_url,
            additional_headers=additional_headers,
            transport=self.transport,
        )


class AsyncEmailCodeAuth(_EmailCodeAuthBase):
    """Async twin of :class:`EmailCodeAuth`."""

    def __init__(
        self,
        client_id: str,
        project: str,
        *,
        session: AuthSession | None = None,
        base_api_url: str | None = None,
        leeway: float = 60.0,
        on_session_change: SessionListener | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        super().__init__(
            client_id,
            project,
            session=session,
            base_api_url=base_api_url,
            leeway=leeway,
            on_session_change=on_session_change,
            clock=clock,
        )
        self.transport = transport
        self._refreshing = asyncio.Lock()

    async def send_code(self, email: str) -> None:
        """Email a one-time code to ``email``."""
        await async_send_email_code(
            email,
            self.client_id,
            self.project,
            base_api_url=self.base_api_url,
            transport=self.transport,
        )

    async def verify_code(self, email: str, code: str) -> AuthSession:
        """Verify the code sent to ``email`` and sign in."""
        generation = self._generation
        token = await async_email_code_token(
            email,
            code,
            self.client_id,
            self.project,
            base_api_url=self.base_api_url,
            transport=self.transport,
        )
        return self._adopt(token, generation)

    def set_session(self, token: OAuthToken | AuthSession) -> AuthSession:
        """Adopt a session obtained elsewhere."""
        if isinstance(token, OAuthToken):
            return self._adopt(token, None)
        self._generation += 1
        self._session = token
        self._notify(token)
        return token

    async def get_session(self) -> AuthSession | None:
        """The current session, refreshed first when within ``leeway`` of
        expiry; ``None`` when signed out."""
        session = self._session
        if session is None:
            return None
        if self._expiring(session):
            return await self.refresh()
        return session

    async def refresh(self) -> AuthSession:
        """Renew the session now, or wait for the renewal in flight. A
        refresh the server rejects signs out and raises
        :class:`~introspection_sdk.AuthenticationError`."""
        session, generation = self._session, self._generation
        if session is None:
            raise _not_signed_in()
        async with self._refreshing:
            if self._generation != generation:
                raise SignInSupersededError(
                    "A sign-out or sign-in completed during the refresh"
                )
            if self._session is not session and self._session is not None:
                return self._session
            refresh_token, session_id, org_id = self._refresh_key(session)
            try:
                token = await async_refresh_access_token(
                    refresh_token,
                    self.client_id,
                    session_id,
                    org_id,
                    base_api_url=self.base_api_url,
                    transport=self.transport,
                )
            except IntrospectionAPIError as exc:
                if not _is_rejection(exc):
                    raise
                if self._generation != generation:
                    raise SignInSupersededError(
                        "A sign-out or sign-in completed during the refresh"
                    ) from exc
                self._clear()
                raise _rejected(exc) from exc
            return self._replace(session, token, generation)

    async def sign_out(self) -> None:
        """Forget the session, then revoke it on the Control Plane. The local
        session is cleared even when revocation fails."""
        session = self._clear()
        if session is None or session.refresh_token is None:
            return
        if session.session_id and session.org_id:
            await async_revoke_session(
                session.session_id,
                session.org_id,
                self.client_id,
                base_api_url=self.base_api_url,
                transport=self.transport,
            )

    async def authorization(self) -> str | None:
        session = await self.get_session()
        return f"Bearer {session.access_token}" if session else None

    async def refresh_after_unauthorized(self, rejected: str | None) -> bool:
        session = await self.get_session()
        if session is None:
            return False
        if (
            rejected is not None
            and rejected != f"Bearer {session.access_token}"
        ):
            return True
        await self.refresh()
        return True

    async def client(
        self,
        *,
        dp_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> AsyncIntrospectionClient:
        """Async twin of :meth:`EmailCodeAuth.client`."""
        # Imported here: the client module imports this one.
        from introspection_sdk.client import AsyncIntrospectionClient

        session = await self.get_session()
        if session is None:
            raise _not_signed_in()
        return AsyncIntrospectionClient(
            credentials=self,
            base_api_url=self.base_api_url,
            dp_url=dp_url or session.dp_url,
            additional_headers=additional_headers,
            transport=self.transport,
        )
