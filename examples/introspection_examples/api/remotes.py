"""Read the protocol of the WebSocket `introspection dev` dials out on: how it
authenticates, its handshake and the frames each side sends.

A project whose Data Plane has no remotes route answers 404; the example says
so and exits 0.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.api.remotes

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, NotFoundError


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient()
    try:
        # #region docs:remotes-connect
        try:
            docs = client.remotes.connect_docs()
        except NotFoundError:
            print("this project's Data Plane has no remotes route")
            return
        print(f"{docs.protocol} at {docs.endpoint}, {docs.encoding} frames")
        print(f"authenticate with {docs.authentication.example}")
        print(f"handshake: {' then '.join(docs.handshake)}")
        for frame in docs.message_protocol.remote_to_cloud:
            print(f"  remote sends {frame.frame}: {frame.description}")
        for frame in docs.message_protocol.cloud_to_remote:
            print(f"  cloud sends {frame.frame}: {frame.description}")
        # #endregion docs:remotes-connect
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
