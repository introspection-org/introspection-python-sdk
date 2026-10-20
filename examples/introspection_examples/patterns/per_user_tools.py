"""Give each end user their own tool access through Pipedream.

Mints a 1-hour consent link for an end user on the project's Pipedream
connector. With a signed-in end user's access token, it also lists that
user's own connections and mints their Connect-button link. Each part is
skipped, with a note, when its prerequisite is missing.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.per_user_tools

Optional env:
    INTROSPECTION_PIPEDREAM_APP  - Pipedream app slug (default gmail)
    INTROSPECTION_USER_TOKEN     - a signed-in end user's access token
    INTROSPECTION_RUNTIME        - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL   - CP REST API host
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def mint_link(
    client: IntrospectionClient, connector_id: UUID, app: str, runtime: str
) -> str:
    # #region docs:patterns/per-user-tools/mint-link
    link = client.connectors.authorize(
        connector_id,
        app=app,
        runtime=runtime,
        identity={"user_id": "user-4821"},
        expires_in=3600,
    )
    # #endregion docs:patterns/per-user-tools/mint-link
    return link.authorize_url


def connect_button(client: IntrospectionClient, app: str, runtime: str) -> str:
    # #region docs:patterns/per-user-tools/verify
    mine = list(client.connections.list(app=app))
    page = client.connections.create(app=app, runtime=runtime)
    # #endregion docs:patterns/per-user-tools/verify
    print(f"the user has {len(mine)} {app} connection(s)")
    return page.authorize_url


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")
    app = os.getenv("INTROSPECTION_PIPEDREAM_APP", "gmail")

    client = IntrospectionClient()
    try:
        pipedream = next(
            (c for c in client.connectors.list() if c.provider == "pipedream"),
            None,
        )
        if pipedream is None:
            print("no Pipedream connector in this project: skipping the link")
        else:
            url = mint_link(client, pipedream.id, app, runtime)
            print(f"send user-4821 this link: {url}")
    finally:
        client.shutdown()

    user_token = os.getenv("INTROSPECTION_USER_TOKEN")
    if not user_token:
        print("INTROSPECTION_USER_TOKEN unset: skipping the Connect button")
        return
    user_client = IntrospectionClient(token=user_token)
    try:
        print(f"Connect button: {connect_button(user_client, app, runtime)}")
    finally:
        user_client.shutdown()


if __name__ == "__main__":
    main()
