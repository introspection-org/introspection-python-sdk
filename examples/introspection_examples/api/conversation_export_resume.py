"""Export a conversation oldest-first, then resume after the saved cursor.

The first export reads the conversation from its start with
``direction="asc"`` and keeps the ``X-Next-Cursor`` cursor the response
answers with. The second passes that cursor as ``next`` and reads only what
arrived since; with nothing newer, the server answers ``204`` and
``export.nothing_newer`` is ``True``. Without ``INTROSPECTION_CONVERSATION``
it takes the newest conversation.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.conversation_export_resume

Optional env:
    INTROSPECTION_CONVERSATION  - conversation id (default: the newest)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def newest_conversation(client: IntrospectionClient) -> str | None:
    records = client.conversations.list(limit=1).page().records
    return records[0].id if records else None


def export_since(
    client: IntrospectionClient, conversation_id: str, cursor: str | None
) -> str | None:
    """Print the spans after ``cursor`` and return the cursor to save."""
    with client.conversations.export_resumable(
        conversation_id, direction="asc", next=cursor
    ) as export:
        if export.nothing_newer:
            print("nothing newer")
        for span in export.iter_spans():
            print(span.span_id, span.name)
    # Opaque: store it as the string it is, never parse it.
    return export.next


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    client = IntrospectionClient()
    try:
        conversation_id = os.getenv(
            "INTROSPECTION_CONVERSATION"
        ) or newest_conversation(client)
        if conversation_id is None:
            print("no conversation to export")
            return
        print(f"exporting {conversation_id} oldest-first")
        cursor = export_since(client, conversation_id, None)
        if cursor is None:
            sys.exit("the export answered no X-Next-Cursor cursor")
        print(f"resuming after {cursor}")
        export_since(client, conversation_id, cursor)
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
