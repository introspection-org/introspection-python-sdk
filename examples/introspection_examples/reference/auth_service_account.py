"""Authentication reference: mint a client from a service-account
application's client credentials.

Backs the "Service-account application" Python block of the docs'
Authentication page (region ``reference/authentication/service-account``).
For the fuller walkthrough that also reads ``dp_url`` and runs a task, see
``introspection_examples.api.service_account``.

Run with:
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID=intro_app_xxx
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET=intro_sk_xxx
    INTROSPECTION_PROJECT=...

        uv run -m introspection_examples.reference.auth_service_account

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import os

from dotenv import load_dotenv

load_dotenv()
_missing = [
    name
    for name in (
        "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID",
        "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET",
        "INTROSPECTION_PROJECT",
    )
    if not os.getenv(name)
]
if _missing:
    raise SystemExit(
        f"missing required env var(s): {', '.join(_missing)} -- create a "
        "service_account Application and export its client id and secret "
        "plus the project slug or id"
    )

# #region docs:reference/authentication/service-account
import os

from introspection_sdk import IntrospectionClient

client = IntrospectionClient.from_service_account(
    client_id=os.environ["INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID"],
    client_secret=os.environ["INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET"],
    project=os.environ["INTROSPECTION_PROJECT"],
)
# #endregion docs:reference/authentication/service-account


def main() -> None:
    try:
        for runtime in client.runtimes.list():
            print(f"runtime {runtime.id}")
            break
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
