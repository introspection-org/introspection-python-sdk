"""Start a routine from a webhook, and by hand with parameters.

Creates a ``webhook`` connector, issues its first secret (shown once), rotates
it and deletes the previous one, creates a prompt routine with a ``webhook``
trigger, then runs the routine by hand with the same parameters, which the SDK
uploads as the run's ``parameters.json``. Cleans both up at the end.

Your own system then calls the control plane's
``/v1/webhooks/connectors/{id}`` with a Standard Webhooks signature (the
``standardwebhooks`` package's ``Webhook(secret).sign(msg_id, timestamp,
data)``), e.g. ``{"type": "order.created", "order_id": "o-123"}``. The run
receives that body as ``parameters.json``, and ``@parameters.order_id`` reads
its top-level ``order_id`` -- the same as the manual run below.

Needs a platform that serves ``/v1/connectors/{id}/secrets``, and an
administrator's credential.

Run with:
    INTROSPECTION_TOKEN=intro_xxx
    INTROSPECTION_RUNTIME_GROUP_ID=<runtime group the routine runs on>

        uv run python -m introspection_examples.api.routine_triggers

Optional env:
    INTROSPECTION_BASE_API_URL      - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL            - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.routines import WebhookTriggerSpec


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime_group_id = os.getenv("INTROSPECTION_RUNTIME_GROUP_ID")
    if not runtime_group_id:
        sys.exit("Set INTROSPECTION_RUNTIME_GROUP_ID to a runtime group id.")

    client = IntrospectionClient(dp_url=os.getenv("INTROSPECTION_DP_URL"))
    try:
        orders = client.connectors.create(
            name="Orders",
            slug="orders-example",
            provider="webhook",
            auth_mode="static",
        )
        # Created without a secret; the platform generates each one and
        # returns it once.
        secrets = client.connectors.secrets
        issued = secrets.create(orders.id, type="standard_webhooks")
        print(f"  issued {issued.id}")  # issued.secret is shown once
        secrets.create(orders.id)  # a rotation keeps the type
        live = list(secrets.list(orders.id))
        for secret in live:
            print(f"  secret {secret.id} {secret.type} {secret.status}")
        secrets.delete(orders.id, live[-1].id)
        print(f"webhook connector {orders.id}")

        routine = client.routines.create(
            name="Order follow-up",
            prompt="Order @parameters.order_id was placed; check stock for it.",
            runtime_group_id=UUID(runtime_group_id),
            triggers=[
                WebhookTriggerSpec(
                    connector_slug="orders-example",
                    event_types=["order.created"],
                )
            ],
        )
        for trigger in routine.triggers:
            print(f"  trigger {trigger.id}: {trigger.type}")

        run = client.routines.trigger(
            routine.id, parameters={"order_id": "o-manual-1"}
        )
        print(
            f"manual run: {run.status} task={run.task_id} {run.reason or ''}"
        )

        client.routines.delete(routine.id)
        client.connectors.delete(orders.id)
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
