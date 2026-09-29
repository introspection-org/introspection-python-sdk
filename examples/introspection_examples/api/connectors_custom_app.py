"""Connect a custom MCP app (Linear by default) end to end.

Finds the app in the open MCP registry, discovers its OAuth server,
creates a connector for it, and mints the consent URL that binds the
app's MCP server to a runtime once a human grants access.

Run with:

    INTROSPECTION_RUNTIME=<runtime slug or runtime group id> \
      uv run python -m introspection_examples.api.connectors_custom_app

Optional env:
    CUSTOM_APP                 - registry search term (default ``linear``)
    MCP_URL                    - use this MCP server URL instead of searching
    CUSTOM_APP_NAME            - connector name (default: the listing's name)
    INTROSPECTION_ENVIRONMENT  - runtime environment lane (default ``production``)
    MCP_SERVER_ID              - the Recipe's MCP server id (default: the slug)
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def _slugify(value: str) -> str:
    kept = "".join(c if c.isalnum() else "-" for c in value.lower())
    return "-".join(part for part in kept.split("-") if part)


def main() -> None:
    runtime = os.getenv("INTROSPECTION_RUNTIME")
    if not runtime:
        raise SystemExit(
            "INTROSPECTION_RUNTIME is required — it names the runtime the "
            "app's MCP server is bound to."
        )
    environment = os.getenv("INTROSPECTION_ENVIRONMENT", "production")
    query = os.getenv("CUSTOM_APP", "linear")

    client = IntrospectionClient()
    try:
        # 1) Find the app's MCP server in the open registry, unless one is
        #    given directly. The search needs no connector and no project.
        mcp_url = os.getenv("MCP_URL")
        app_name = os.getenv("CUSTOM_APP_NAME")
        if not mcp_url:
            listings = client.connectors.search_custom_apps(query, limit=10)
            listing = next((app for app in listings if app.mcp_url), None)
            if listing is None or listing.mcp_url is None:
                raise SystemExit(
                    f"No MCP server listed for {query!r}; set MCP_URL instead"
                )
            mcp_url = listing.mcp_url
            app_name = app_name or listing.name
            print(f"registry -> {listing.name}: {mcp_url}")
        app_name = app_name or query.title()

        # 2) Discover the OAuth server behind the MCP URL. This may
        #    register an OAuth client with the provider and return its
        #    credentials; they are passed to create below so a second
        #    client is not registered.
        discovery = client.connectors.discover_oauth(mcp_url)
        print(
            f"oauth -> issuer={discovery.issuer}, "
            f"registration={discovery.client_registration or 'manual'}, "
            f"scopes={discovery.scopes_supported or '-'}"
        )

        # 3) Create the connector. A custom app named "Linear" gets
        #    provider `linear`, which is runtime-bound: authorize must name
        #    a runtime. Re-running replaces the live connector's
        #    configuration for this slug rather than duplicating it.
        slug = _slugify(app_name)
        host = urlsplit(mcp_url).hostname
        connector = client.connectors.create(
            name=app_name,
            slug=slug,
            provider=slug,
            auth_mode="oauth_stored",
            environment=environment,
            issuer=mcp_url,
            api_hosts=[host] if host else None,
            client_id=discovery.client_id,
            client_secret=discovery.client_secret,
            scopes=discovery.scopes_supported or None,
        )
        print(f"connector -> {connector.slug} ({connector.id})")

        # 4) Mint the consent URL. `binding` names the MCP endpoint the
        #    grant completes into: on success the control plane writes it
        #    in the same transaction as the connection, so the runtime is
        #    never authorized but unbound.
        authorization = client.connectors.authorize(
            connector.id,
            runtime=runtime,
            binding={
                "environment": environment,
                "mcp_server_id": os.getenv("MCP_SERVER_ID", slug),
                "url": mcp_url,
            },
        )

        # 5) A human opens this link to grant access.
        print(f"{app_name} authorization -> {authorization.authorize_url}")
        print(f"  valid for {authorization.expires_in}s")
    finally:
        client.shutdown()


if __name__ == "__main__":
    load_dotenv()
    main()
