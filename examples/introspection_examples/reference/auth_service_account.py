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

Without those variables it prints a skip message and exits 0, so the
examples workflow can list it whether or not service-account secrets are
configured.

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import os
import sys

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
    # Not an error: the examples workflow runs this module whether or not
    # the repository has service-account secrets configured.
    print(
        f"skipping: set {', '.join(_missing)} (a service_account "
        "Application's client id and secret, and the project slug or id) "
        "to run this example",
        file=sys.stderr,
    )
    raise SystemExit(0)

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
