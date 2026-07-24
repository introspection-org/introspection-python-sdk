"""Service-account (machine) auth — mint a token from confidential
credentials, then run a stable Runtime.

This is the headless / CI counterpart to a long-lived ``intro_…`` API
key: the confidential Application's ``client_id`` / ``client_secret``
stay server-side, and you re-mint when the token expires.

``IntrospectionClient.from_service_account(...)`` mints and constructs a ready
client in one call. The usual ``client.runtimes.run(runtime=slug)`` flow then
works unchanged.

Run with:
    INTRO_SA_CLIENT_ID=intro_app_xxx
    INTRO_SA_CLIENT_SECRET=intro_sk_xxx
    INTRO_PROJECT=...

        uv run python -m introspection_examples.api.service_account

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or group ID (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os

from introspection_sdk import IntrospectionClient


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"missing required env var: {name}")
    return value


def main() -> None:
    client_id = _require("INTRO_SA_CLIENT_ID")
    client_secret = _require("INTRO_SA_CLIENT_SECRET")
    project = _require("INTRO_PROJECT")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    # Mint-and-construct: the simplest path for a server/CI caller.
    client = IntrospectionClient.from_service_account(
        client_id=client_id,
        client_secret=client_secret,
        project=project,
    )

    runner = client.runtimes.run(runtime=runtime, project=project)
    try:
        run = runner.tasks.start(prompt="Say hello in one sentence.")
        for event in run.stream():
            print(event.model_dump_json(by_alias=True, exclude_none=True))
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
