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
* A business member's device-code login, the one ``introspection login``
  runs: :func:`request_device_code`, then :func:`wait_for_device_token`
  (or :func:`poll_device_token` once per poll). The login refreshes with
  :func:`refresh_access_token` (``client_id="cli"``), trades its access
  token for an ``introspection dev`` credential with
  :func:`development_credential`, and signs out with :func:`oidc_logout`.

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
import threading
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import httpx2 as httpx

from introspection_sdk._async.auth import (
    GRANT_EMAIL_CODE,
    AsyncCredentialProvider,
    async_authorization_code_token,
    async_email_code_token,
    async_refresh_access_token,
    async_revoke_session,
    async_send_email_code,
    async_service_account_token,
    async_token_exchange,
)
from introspection_sdk._async.device_code import (
    async_development_credential,
    async_oidc_logout,
    async_poll_device_token,
    async_request_device_code,
    async_wait_for_device_token,
)
from introspection_sdk._auth_common import (
    AuthSession,
    EmailCodeAuthBase,
    OAuthToken,
    SessionListener,
    SignInSupersededError,
    _utcnow,
)
from introspection_sdk._device_code_common import (
    DEVICE_CODE_GRANT,
    DEVICE_FLOW_CLIENT_ID,
    DeviceCode,
    DeviceTokenPoll,
    DeviceTokenStatus,
)
from introspection_sdk._errors import (
    AuthenticationError,
    IntrospectionAPIError,
    ValidationError,
)
from introspection_sdk._sync.auth import (
    CredentialProvider,
    authorization_code_token,
    email_code_token,
    refresh_access_token,
    revoke_session,
    send_email_code,
    service_account_token,
    token_exchange,
)
from introspection_sdk._sync.device_code import (
    development_credential,
    oidc_logout,
    poll_device_token,
    request_device_code,
    wait_for_device_token,
)

if TYPE_CHECKING:
    from introspection_sdk.client import (
        AsyncIntrospectionClient,
        IntrospectionClient,
    )

__all__ = [
    "DEVICE_CODE_GRANT",
    "DEVICE_FLOW_CLIENT_ID",
    "GRANT_EMAIL_CODE",
    "AsyncCredentialProvider",
    "AsyncEmailCodeAuth",
    "AuthSession",
    "CredentialProvider",
    "DeviceCode",
    "DeviceTokenPoll",
    "DeviceTokenStatus",
    "EmailCodeAuth",
    "OAuthToken",
    "SignInSupersededError",
    "async_authorization_code_token",
    "async_development_credential",
    "async_email_code_token",
    "async_oidc_logout",
    "async_poll_device_token",
    "async_refresh_access_token",
    "async_request_device_code",
    "async_revoke_session",
    "async_send_email_code",
    "async_service_account_token",
    "async_token_exchange",
    "async_wait_for_device_token",
    "authorization_code_token",
    "development_credential",
    "email_code_token",
    "oidc_logout",
    "poll_device_token",
    "refresh_access_token",
    "request_device_code",
    "revoke_session",
    "send_email_code",
    "service_account_token",
    "token_exchange",
    "wait_for_device_token",
]


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


# EmailCodeAuth and AsyncEmailCodeAuth are written by hand rather than
# generated from one async source: the sync twin guards its state with
# thread locks that the async twin, on one event loop, does not take.
class EmailCodeAuth(EmailCodeAuthBase):
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


class AsyncEmailCodeAuth(EmailCodeAuthBase):
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
