"""Gemini SDK + Arize dual export via introspection.init().

Demonstrates dual export: Gemini calls (including thought signatures) are sent
to both Arize and Introspection. Phoenix's ``register()`` sets up the Arize
exporter on the global TracerProvider; ``introspection.init()`` then detects
that provider and attaches Introspection's pipeline, so one set of spans fans
out to both backends. No per-framework wiring, and no third-party Gemini
instrumentor required.

Run with:
    uv run -m introspection_examples.otel.gemini_sdk.gemini_arize_init

Required env vars:
    GEMINI_API_KEY     - Google Gemini API key
    ARIZE_SPACE_KEY    - Arize space id
    ARIZE_API_KEY      - Arize API key
    INTROSPECTION_TOKEN - Introspection API token
"""

import os
from typing import Any, cast

from dotenv import load_dotenv

try:
    from google import genai
    from phoenix.otel import register
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: "
        "uv sync --extra arize --extra gemini"
    ) from e

import introspection_sdk.otel as introspection

GEMINI_MODEL = "gemini-3.1-pro-preview"


def main() -> None:
    load_dotenv()

    # 1. Arize exporter on the global provider (register() sets it global).
    register(
        project_name="dual-export-init",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ.get("ARIZE_SPACE_KEY", ""),
            "api_key": os.environ.get("ARIZE_API_KEY", ""),
        },
    )

    # 2. init() detects the provider + instruments Gemini -> dual export.
    introspection.init(service_name="gemini-arize-init")

    client = genai.Client()
    with introspection.conversation():
        response = cast(Any, client.models.generate_content)(
            model=GEMINI_MODEL,
            contents="Say hello in one word.",
        )

    print((response.text or "").strip())
    introspection.get_tracer_provider().force_flush()
    print("✓ Exported to Arize + Introspection.")


if __name__ == "__main__":
    main()
