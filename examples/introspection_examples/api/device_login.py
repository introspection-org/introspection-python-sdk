"""Sign a member in with the device-code login `introspection login` runs.

Requests a device code, prints where to approve it and polls once. The login
itself takes a person in a browser, so the example then stops, unless
INTROSPECTION_DEVICE_LOGIN_WAIT=1: it then waits for the approval, refreshes
the login, trades it for a development credential and signs out again.

Run with:
    uv run -m introspection_examples.api.device_login

Optional env:
    INTROSPECTION_DEVICE_LOGIN_WAIT  - 1 to wait for a person to approve
    INTROSPECTION_BASE_API_URL       - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from introspection_sdk.auth import (
    DEVICE_FLOW_CLIENT_ID,
    development_credential,
    oidc_logout,
    poll_device_token,
    refresh_access_token,
    request_device_code,
    wait_for_device_token,
)


def main() -> None:
    load_dotenv()
    # #region docs:device-login
    device = request_device_code()
    print(f"Open {device.verification_uri} and enter {device.user_code}")
    # One poll, for a client with its own loop; `authorization_pending` so far.
    poll = poll_device_token(device.device_code.get_secret_value())
    print(f"login is {poll.status}")
    # #endregion docs:device-login
    if os.getenv("INTROSPECTION_DEVICE_LOGIN_WAIT") != "1":
        print(
            "Set INTROSPECTION_DEVICE_LOGIN_WAIT=1 to wait for the approval."
        )
        return

    # #region docs:device-login-session
    login = wait_for_device_token(device)
    print(f"signed in to org {login.org_id} as {login.member_name}")
    # Rotates the refresh token: keep the new one.
    login = refresh_access_token(
        login.refresh_token or "",
        DEVICE_FLOW_CLIENT_ID,
        login.session_id or "",
        login.org_id or "",
    )
    # A development login only; anything else is a ValidationError.
    credential = development_credential(login.access_token)
    print(f"development credential lasts {credential.expires_in}s")
    oidc_logout(login.cp_session or "")
    # #endregion docs:device-login-session


if __name__ == "__main__":
    main()
