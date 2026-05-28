"""Gemini one-liner example: ``introspection.init()`` auto-detects Gemini.

A single ``introspection.init()`` call instruments the installed ``google-genai``
SDK (capturing thought signatures) and wires it into Introspection's trace
pipeline — no per-framework setup. Contrast with ``gemini_native.py``, which
shows the explicit standalone instrumentor.

Run with:
    export INTROSPECTION_TOKEN=...
    export GEMINI_API_KEY=...
    uv run -m introspection_examples.otel.gemini_sdk.gemini_init
"""

from typing import Any, cast

try:
    from google import genai
    from google.genai import types
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: pip install google-genai"
    ) from e

import introspection_sdk.otel as introspection

GEMINI_MODEL = "gemini-3.1-pro-preview"


def main() -> None:
    # One line: detects google-genai (and any other installed frameworks)
    # and wires them into the shared trace pipeline.
    introspection.init(service_name="gemini-init-example")

    client = genai.Client()
    with introspection.conversation():
        response = cast(Any, client.models.generate_content)(
            model=GEMINI_MODEL,
            contents="What is 2+2? Think step by step.",
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=True),
            ),
        )
        print(response.text)


if __name__ == "__main__":
    main()
