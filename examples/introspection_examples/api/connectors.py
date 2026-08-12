"""B2B2C connector walkthrough — the flow a Business runs from its own
backend, without ever touching the Introspection UI.

Creates a Slack connector for the org, mints the install link that gets
handed to a customer, then lists the workspaces that connected and
(optionally) disconnects one.

Run with:
    INTROSPECTION_TOKEN=intro_xxx
    SLACK_CLIENT_ID=<your Slack app client id>
    SLACK_CLIENT_SECRET=<your Slack app client secret>
    INTROSPECTION_RUNTIME=<runtime slug or runtime group id>

        uv run python -m introspection_examples.api.connectors

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
    REVOKE_FIRST_CONNECTION=1   - revoke the first listed connection (destructive)

Connectors sit behind a server-side feature flag. If every call 404s with
"Connectors are not enabled", the deployment has not opted in yet.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def main() -> None:
    client_id = os.getenv("SLACK_CLIENT_ID")
    client_secret = os.getenv("SLACK_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit(
            "SLACK_CLIENT_ID and SLACK_CLIENT_SECRET are required — "
            "they are your own Slack app's credentials."
        )

    client = IntrospectionClient()
    try:
        # 1) Create the connector — the org-level definition of the
        #    provider: your Slack app's credentials and the scopes it asks
        #    for. Create is idempotent on `slug`, so re-running this
        #    returns the existing row rather than a duplicate.
        #    `client_secret` is write-only: it goes up here and is absent
        #    from every response.
        #
        #    This assumes the Slack app already exists. Registering a new one
        #    is a second pass: its delivery URL contains the connector id
        #    ({cp-host}/v1/webhooks/slack/{connector.id}), so the connector
        #    has to exist first, and the credentials come back afterwards via
        #    client.connectors.update(connector.id, webhook_url=..., ...).
        connector = client.connectors.create(
            name="Slack (support)",
            slug="slack-support",
            provider="slack",
            auth_mode="oauth_stored",
            scopes=["chat:write", "channels:read", "app_mentions:read"],
            api_hosts=["slack.com"],
            client_id=client_id,
            client_secret=client_secret,
        )
        print(
            f"connector -> {connector.slug} ({connector.id}), "
            f"status={connector.status}"
        )

        # 2) Mint the install link. This is the whole point of the SDK
        #    surface: the URL below is what you put in front of *your*
        #    customer, in your own product, so their Slack workspace
        #    connects to an agent.
        #
        #    `requires_runtime` is derived server-side from the provider —
        #    read it rather than hardcoding which providers are chat
        #    providers. When it is True, `runtime` names the agent that
        #    answers the messages, and omitting it is a 422.
        runtime = os.getenv("INTROSPECTION_RUNTIME")
        if connector.requires_runtime and not runtime:
            raise SystemExit(
                f"{connector.provider} delivers conversations, so "
                "INTROSPECTION_RUNTIME must name the runtime that replies."
            )

        install = client.connectors.authorize(
            connector.id,
            runtime=runtime,
            # The default (600s) suits following the link immediately.
            # Raise it when the link is emailed to someone else — an admin
            # does not open it in ten minutes. The ceiling is one day.
            expires_in=3600,
        )
        print(f"install link -> {install.authorize_url}")
        print(
            f"  valid for {install.expires_in}s "
            f"(until {install.expires_at.isoformat()})"
        )
        #    The URL carries a single-use `state`: it is a bearer capability
        #    for exactly one install. Hand it to one recipient, do not cache
        #    it, and mint a fresh one per customer — two calls return two
        #    different URLs.

        # 3) List what connected. For Slack each connection is one
        #    workspace that completed the install; `member_id` is the
        #    workspace's customer member and `runtime_group_id` is the
        #    agent answering it. Tokens are never serialized.
        connections = list(client.connectors.connections.list(connector.id))
        for connection in connections:
            print(
                f"  connection {connection.id}: "
                f"subject={connection.subject_type}, "
                f"status={connection.status}, "
                f"member={connection.member_id or '-'}"
            )
        if not connections:
            print("  (none yet — open the install link above to connect one)")

        # 4) Disconnect one. Revoking destroys the provider token behind
        #    that one connection; the connector and its other connections
        #    are untouched, and the customer must re-consent through a
        #    fresh install link.
        if os.getenv("REVOKE_FIRST_CONNECTION") == "1" and connections:
            client.connectors.connections.revoke(
                connector.id, connections[0].id
            )
            print(f"revoked connection {connections[0].id}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    load_dotenv()
    main()
