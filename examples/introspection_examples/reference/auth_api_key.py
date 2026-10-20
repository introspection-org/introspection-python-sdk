"""Authentication reference: construct a client from a project API key.

Backs the "API key" Python block of the docs' Authentication page
(region ``reference/authentication/api-key``).

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.reference.auth_api_key

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import os

from dotenv import load_dotenv

load_dotenv()
if not os.getenv("INTROSPECTION_TOKEN"):
    raise SystemExit(
        "INTROSPECTION_TOKEN is not set: export a project API key "
        "(intro_...) or add it to .env"
    )

# #region docs:reference/authentication/api-key
import os

from introspection_sdk import IntrospectionClient

client = IntrospectionClient()

# Or pass it explicitly.
explicit = IntrospectionClient(token=os.environ["INTROSPECTION_TOKEN"])
# #endregion docs:reference/authentication/api-key


def main() -> None:
    try:
        for runtime in client.runtimes.list():
            print(f"runtime {runtime.id}")
            break
    finally:
        client.shutdown()
        explicit.shutdown()


if __name__ == "__main__":
    main()
