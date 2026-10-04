"""Label members with metadata and find them by it.

Lists the organization's members filtered by a metadata pair, then (when
INTROSPECTION_MEMBER_ID is set) replaces that member's metadata map.
Updating needs a token with ``members:manage``.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.members

Optional env:
    INTROSPECTION_MEMBER_ID     - member to label (default: list only)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient()
    try:
        member_id = os.getenv("INTROSPECTION_MEMBER_ID")
        if member_id:
            # Replaces the whole map; {} would clear it.
            member = client.members.update(
                UUID(member_id), metadata={"plan": "enterprise"}
            )
            print(f"labelled {member.id}: {member.metadata}")

        # A Pager: iterating follows the `next` cursor across pages.
        for member in client.members.list(
            metadata={"plan": "enterprise"}, limit=50
        ):
            print(f"  {member.member_type:9} {member.id} {member.metadata}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
