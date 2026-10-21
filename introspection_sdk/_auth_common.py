"""Code shared by the sync and async twins in :mod:`introspection_sdk.auth`."""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from introspection_sdk._errors import (
    AuthenticationError,
)

_DEFAULT_BASE_API_URL = "https://api.introspection.dev"


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
