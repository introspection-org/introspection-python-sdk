"""Native email-code sign-in — an end user signs in with a code sent to
their email, then reads their own data on the Data Plane.

Needs a ``native`` Application (its ``client_id``) and the project its users
sign in to. The code is typed in at the prompt: a returning user's is six
digits, a new user's first one is six letters and digits.

The session is kept in ``.introspection-session.json`` so a second run signs
in without a new code; delete the file to sign in again. The access token is
renewed before it expires and after a ``401``.

Run with:
    INTRO_NATIVE_CLIENT_ID=intro_app_xxx
    INTRO_PROJECT=...
    INTRO_EMAIL=user@example.com

        uv run python -m introspection_examples.api.native_email_code

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from introspection_sdk import AuthSession, EmailCodeAuth
from introspection_sdk.schemas.events import IntrospectionEventName

SESSION_FILE = Path(".introspection-session.json")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"missing required env var: {name}")
    return value


def _persist(session: AuthSession | None) -> None:
    if session is None:
        SESSION_FILE.unlink(missing_ok=True)
    else:
        SESSION_FILE.write_text(session.model_dump_json())
        SESSION_FILE.chmod(0o600)


def main() -> None:
    load_dotenv()
    client_id = _require("INTRO_NATIVE_CLIENT_ID")
    project = _require("INTRO_PROJECT")
    email = _require("INTRO_EMAIL")

    restored = (
        AuthSession.model_validate_json(SESSION_FILE.read_text())
        if SESSION_FILE.exists()
        else None
    )
    auth = EmailCodeAuth(
        client_id,
        project,
        session=restored,
        on_session_change=_persist,
    )

    if auth.get_session() is None:
        auth.send_code(email)
        auth.verify_code(email, input(f"Code sent to {email}: "))

    session = auth.get_session()
    assert session is not None
    print(f"signed in as member {session.member_id} (scope: {session.scope})")

    # Only the Data Plane namespaces accept this token.
    client = auth.client()
    try:
        page = client.events.list(
            IntrospectionEventName.FEEDBACK, limit=5
        ).page()
        print(f"{page.count} recent feedback events")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
