"""Start a routine from a webhook, and by hand with parameters.

Creates a ``webhook`` connector (its secret is shown once), a prompt routine
with a ``connector`` trigger that reads ``order_id`` from the call's JSON body
into ``@parameters.order_id``, then runs the routine by hand with the same
parameter. Cleans both up at the end.

Your own system then calls the control plane's
``/v1/webhooks/connectors/{id}`` with a Standard Webhooks signature, e.g.
``{"type": "order.created", "data": {"id": "o-123"}}``, and the routine runs
with ``order_id = "o-123"``.

Needs a platform with introspection-cloud#4052 deployed, and an
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
from introspection_sdk.schemas.routines import RoutineTriggerSpec


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
        # The platform generates the secret and returns it once.
        assert orders.signing_secret is not None
        print(f"webhook connector {orders.id} ({orders.webhook_auth})")

        routine = client.routines.create(
            name="Order follow-up",
            trigger_type="manual",
            prompt="Order @parameters.order_id was placed; check stock for it.",
            runtime_group_id=UUID(runtime_group_id),
            triggers=[
                RoutineTriggerSpec(
                    source="connector",
                    provider="webhook",
                    connector_slug="orders-example",
                    event_types=["order.created"],
                    parameters={"order_id": "/data/id"},
                )
            ],
        )
        for trigger in routine.triggers:
            print(f"  trigger {trigger.id}: {trigger.event_types}")

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
