"""Create a Pipedream connector and authorize one downstream application.

Run with either an existing connector id or Pipedream project credentials:

    INTROSPECTION_RUNTIME=<runtime slug or runtime group id> \
    PIPEDREAM_CONNECTOR_ID=<connector UUID> \
      uv run python -m introspection_examples.api.connectors_pipedream

When ``PIPEDREAM_CONNECTOR_ID`` is omitted, set ``PIPEDREAM_PROJECT_ID``,
``PIPEDREAM_CLIENT_ID``, and ``PIPEDREAM_CLIENT_SECRET``. ``PIPEDREAM_APP``
defaults to ``google_sheets``. Set ``PIPEDREAM_PROGRESSIVE_SCOPES=true`` only
when the runtime can tolerate a user granting fewer scopes.
"""

from __future__ import annotations

import os
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def main() -> None:
    runtime = os.getenv("INTROSPECTION_RUNTIME")
    requested_app = os.getenv("PIPEDREAM_APP", "google_sheets")
    if not runtime:
        raise SystemExit("INTROSPECTION_RUNTIME is required")

    client = IntrospectionClient()
    try:
        connector_id_raw = os.getenv("PIPEDREAM_CONNECTOR_ID")
        if connector_id_raw:
            connector_id = UUID(connector_id_raw)
        else:
            project_id = os.getenv("PIPEDREAM_PROJECT_ID")
            client_id = os.getenv("PIPEDREAM_CLIENT_ID")
            client_secret = os.getenv("PIPEDREAM_CLIENT_SECRET")
            if not project_id or not client_id or not client_secret:
                raise SystemExit(
                    "Set PIPEDREAM_CONNECTOR_ID, or PIPEDREAM_PROJECT_ID, "
                    "PIPEDREAM_CLIENT_ID, and PIPEDREAM_CLIENT_SECRET"
                )

            connector = client.connectors.create(
                name="Pipedream Connect",
                slug="pipedream-connect",
                provider="pipedream",
                auth_mode="client_credentials",
                client_id=client_id,
                client_secret=client_secret,
                metadata={"pipedream_project_id": project_id},
            )
            connector_id = connector.id
            print(f"connector -> {connector.slug} ({connector.id})")

        applications = client.connectors.list_apps(
            connector_id, query=requested_app, limit=5
        )
        application = next(
            (item for item in applications if item.slug == requested_app), None
        )
        if application is None:
            raise SystemExit(
                f"Pipedream application not found: {requested_app}"
            )

        authorization = client.connectors.authorize(
            connector_id,
            runtime=runtime,
            app=application.slug,
            allow_progressive_scopes=os.getenv("PIPEDREAM_PROGRESSIVE_SCOPES")
            == "true",
        )
        print(
            f"{application.name} authorization -> {authorization.authorize_url}"
        )
    finally:
        client.shutdown()


if __name__ == "__main__":
    load_dotenv()
    main()
