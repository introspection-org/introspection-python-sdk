"""The token broker behind a browser chat: mint a short-lived session for
the signed-in user so credentials never reach the browser.

``create_session`` is the body of a ``POST /api/introspection/session``
route and returns the JSON the browser connects with; answer it with
``Cache-Control: no-store``. ``create_federated_session`` is the same route
for users signed in through your own identity provider. Run directly, the
module calls the broker for one sample user and prints what the browser
would receive, without the token itself.

Run with:
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID=intro_app_xxx
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET=intro_sk_xxx
    INTROSPECTION_PROJECT=<project-slug>

        uv run -m introspection_examples.patterns.web_chat

Optional env:
    INTROSPECTION_FEDERATED_CLIENT_ID  - federated application's client ID
    INTROSPECTION_ID_TOKEN             - an ID token from your identity provider
    INTROSPECTION_RUNTIME              - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL         - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, token_exchange

REQUIRED_ENV = (
    "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID",
    "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET",
    "INTROSPECTION_PROJECT",
)

load_dotenv()
# The docs use support-agent; point this at any deployed runtime.
RUNTIME = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")


def create_session(user_id: str) -> dict[str, str]:
    """POST /api/introspection/session for the user in your session.

    Authenticate and rate-limit first; send ``Cache-Control: no-store``.
    """
    # Service-account tokens last 60 minutes and never refresh: cache below.
    cp = IntrospectionClient.from_service_account(
        client_id=os.environ["INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID"],
        client_secret=os.environ[
            "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET"
        ],
        project=os.environ["INTROSPECTION_PROJECT"],
    )
    runtime = cp.runtimes.resolve(RUNTIME)
    session = cp.runtimes.handle(runtime.id).run(identity={"user_id": user_id})
    return {
        "token": session.spec.session_token,
        "runtimeId": str(runtime.id),
        "dpUrl": session.dp_endpoint,
    }


# #region docs:patterns/web-chat/federated-broker
def create_federated_session(id_token: str, runtime_id: str) -> dict[str, str]:
    """The broker for users signed in through your identity provider.

    An end-user token can't look up runtimes: take ``runtime_id`` from config.
    """
    token = token_exchange(
        subject_token=id_token,
        client_id=os.environ["INTROSPECTION_FEDERATED_CLIENT_ID"],
        project=os.environ["INTROSPECTION_PROJECT"],
    )
    return {
        "token": token.access_token,
        "runtimeId": runtime_id,
        "dpUrl": token.dp_url or "",
    }


# #endregion docs:patterns/web-chat/federated-broker


def main() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        # Not an error: the examples workflow runs this module whether or
        # not the repository has service-account secrets configured.
        print(
            f"skipping: set {', '.join(missing)} (a service account's client "
            "ID and secret, and its project slug) to run this example",
            file=sys.stderr,
        )
        return

    session = create_session("user-4821")
    print(
        f"broker -> runtimeId={session['runtimeId']} dpUrl={session['dpUrl']}"
    )

    id_token = os.getenv("INTROSPECTION_ID_TOKEN")
    if not (id_token and os.getenv("INTROSPECTION_FEDERATED_CLIENT_ID")):
        print("no federated sign-in configured: skipping the exchange")
        return
    federated = create_federated_session(id_token, session["runtimeId"])
    print(f"federated broker -> dpUrl={federated['dpUrl']}")


if __name__ == "__main__":
    main()
