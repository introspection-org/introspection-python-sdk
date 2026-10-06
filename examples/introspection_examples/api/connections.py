"""List a member's connected apps, and start connecting one.

Uses ``client.connections``; ``runner.connections`` is the same namespace,
with ``create`` defaulting ``runtime`` to the runner's runtime group.

Run with:
    INTROSPECTION_TOKEN=<a member's token>

        uv run python -m introspection_examples.api.connections

Optional env:
    INTROSPECTION_CONNECT_APP      - app slug to connect, e.g. gmail
    INTROSPECTION_RUNTIME          - runtime slug or group id the connection serves
    INTROSPECTION_BASE_API_URL     - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL           - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to a member's Introspection token.")

    client = IntrospectionClient(dp_url=os.getenv("INTROSPECTION_DP_URL"))
    try:
        for connection in client.connections.list():
            state = "healthy" if connection.healthy else "reconnect"
            print(f"  {connection.app:16} {state:9} {connection.account_name}")

        app = os.getenv("INTROSPECTION_CONNECT_APP")
        runtime = os.getenv("INTROSPECTION_RUNTIME")
        if not (app and runtime):
            return

        page = client.connections.create(app=app, runtime=runtime)
        print(f"open within {page.expires_in}s: {page.authorize_url}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
