"""Read a project's AAuth inbox: the missions its people approved agents to
carry out, and the approvals agents are waiting on.

A project whose Data Plane runs no Person Server answers 404; the example
says so and exits 0.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.api.aauth_inbox

Optional env:
    INTROSPECTION_AAUTH_DENY_AS - a member id: deny every pending approval as them
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, NotFoundError
from introspection_sdk.schemas.aauth import ApprovalStatus


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient()
    try:
        # #region docs:aauth-inbox
        try:
            # Pagers: iterating follows the `next` cursor across pages.
            for mission in client.aauth.missions.list(limit=20):
                budget = mission.budget
                spend = (
                    f"{mission.spent}/{budget.amount} {budget.unit}"
                    if budget
                    else "no budget"
                )
                print(f"mission {mission.id} {mission.mission!r} ({spend})")
            for approval in client.aauth.approvals.list(
                status=[ApprovalStatus.PENDING]
            ):
                print(
                    f"pending {approval.kind} for {approval.agent_id}: "
                    f"{approval.description}"
                )
                member_id = os.getenv("INTROSPECTION_AAUTH_DENY_AS")
                if member_id:
                    denied = client.aauth.approvals.decide(
                        approval.id, status="denied", member_id=member_id
                    )
                    print(f"{denied.id} is now {denied.status}")
        except NotFoundError:
            print("this project's Data Plane runs no AAuth Person Server")
        # #endregion docs:aauth-inbox
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
