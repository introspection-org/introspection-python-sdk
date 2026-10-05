"""Log an app event under a custom name, then read it back.

Emits one ``ark.feed.entry`` event with a stable ``event_id`` (so a re-run
is recognisable as the same entry), flushes, and lists the last day of
``introspection.track`` events, keeping only that name client-side. The
platform indexes events asynchronously, so a just-logged event can take a
moment to appear in the read.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.otel.log_event

Optional env:
    INTROSPECTION_BASE_OTEL_URL  - OTLP collector (default https://otel.introspection.dev)
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.otel import IntrospectionLogs
from introspection_sdk.schemas import TrackEvent

EVENT_NAME = "ark.feed.entry"


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    logs = IntrospectionLogs(service_name="introspection-examples")
    try:
        logs.log_event(
            EVENT_NAME,
            {"entry_id": "e_1", "source": "rss", "score": 0.92},
            event_id="feed-entry:e_1",
            timestamp=datetime.now(UTC),
        )
        logs.flush()
    finally:
        logs.shutdown()
    print(f"logged {EVENT_NAME}")

    client = IntrospectionClient()
    try:
        # No server-side `name` filter yet: filter on payload.name here.
        for event in client.events.list(
            "introspection.track", lookback="24h", limit=50
        ):
            if not isinstance(event, TrackEvent):
                continue
            if event.payload.name != EVENT_NAME:
                continue
            print(f"  {event.timestamp} {event.id} {event.payload.properties}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
