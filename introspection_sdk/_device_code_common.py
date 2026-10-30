"""Models both twins of :mod:`introspection_sdk.auth`'s device-code login
share."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, SecretStr

from introspection_sdk._auth_common import OAuthToken

#: The ``grant_type`` the token endpoint takes a device code under.
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
#: The first-party CLI client, the only ``client_id`` the Control Plane lets
#: start the device flow today.
DEVICE_FLOW_CLIENT_ID = "cli"

#: The poll interval when the server names none (RFC 8628 §3.2).
DEFAULT_INTERVAL_SECONDS = 5
#: ``slow_down`` adds this much to the interval (RFC 8628 §3.5).
SLOW_DOWN_SECONDS = 5
#: ``interval: 0`` would poll in a tight loop and a huge one would sleep past
#: the code's expiry; neither is honoured.
MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 60
#: No server keeps a code alive longer than this.
MAX_EXPIRES_IN_SECONDS = 30 * 60


class DeviceCode(BaseModel):
    """CP ``POST /v1/oauth/device/code`` response (RFC 8628 §3.2).

    Show ``user_code`` and ``verification_uri`` (or open
    ``verification_uri_complete``), then poll the token endpoint with
    ``device_code``."""

    model_config = ConfigDict(extra="allow")

    device_code: SecretStr
    """Whoever holds it receives the tokens once the member approves."""
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int = DEFAULT_INTERVAL_SECONDS


class DeviceTokenStatus(StrEnum):
    """One poll's answer (RFC 8628 §3.5)."""

    TOKEN = "token"
    """The member approved; :attr:`DeviceTokenPoll.token` holds the login."""
    PENDING = "authorization_pending"
    SLOW_DOWN = "slow_down"
    ACCESS_DENIED = "access_denied"
    EXPIRED = "expired_token"


class DeviceTokenPoll(BaseModel):
    """One poll of the token endpoint, classified."""

    status: DeviceTokenStatus
    token: OAuthToken | None = None


__all__ = [
    "DEVICE_CODE_GRANT",
    "DEVICE_FLOW_CLIENT_ID",
    "DeviceCode",
    "DeviceTokenPoll",
    "DeviceTokenStatus",
]
