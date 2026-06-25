"""Service-account (machine) auth — mint a token from confidential
credentials, then resolve a runtime and run a task.

This is the headless / CI counterpart to a long-lived ``intro_…`` API
key: the confidential Application's ``client_id`` / ``client_secret``
stay server-side, and you re-mint when the token expires.

Two ways to use it, both shown below:

1. ``IntrospectionClient.from_service_account(...)`` — mint and construct
   a ready client in one call. The usual ``client.runtimes(slug).run()``
   flow then works unchanged.
2. ``service_account_token(...)`` directly — when you also need the
   resolved ``dp_url`` (the Data Plane endpoint the CP picked for the
   project) and the ``runtime_id``, e.g. a broker that hands a browser
   client ``{ token, runtime_id, dp_url }`` so the SPA talks only to the
   Data Plane and never resolves runtimes itself.

Run with:
    INTRO_SA_CLIENT_ID=intro_app_xxx
    INTRO_SA_CLIENT_SECRET=intro_sk_xxx
    INTRO_PROJECT=...

        uv run python -m introspection_examples.api.service_account

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os

from introspection_sdk import IntrospectionClient, service_account_token


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

    # (1) Mint-and-construct: the simplest path for a server/CI caller.
    client = IntrospectionClient.from_service_account(
        client_id=client_id,
        client_secret=client_secret,
        project=project,
    )

    # (2) Broker path: mint the token explicitly to also read `dp_url`
    # (resolved server-side by the CP), and resolve the runtime slug to a
    # concrete `runtime_id`. A web broker returns these three to a browser
    # client — `{ token, runtime_id, dp_url }` — so the SPA connects to the
    # Data Plane directly without hardcoding the DP URL.
    token = service_account_token(
        client_id=client_id,
        client_secret=client_secret,
        project=project,
    )
    resolved_runtime = client.runtimes.resolve(runtime, project=project)
    print(f"runtime_id={resolved_runtime.id}, dp_url={token.dp_url}")

    runner = client.runtimes(runtime).run()
    try:
        run = runner.tasks.start(prompt="Say hello in one sentence.")
        for event in run.stream():
            print(event.model_dump_json(by_alias=True, exclude_none=True))
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
