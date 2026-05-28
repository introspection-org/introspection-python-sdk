"""
Gemini Native Instrumentation Example

Uses Introspection's GeminiInstrumentor to capture the full Gemini response
including thought signatures — encrypted reasoning state tokens that Gemini
3.x returns alongside text and function-call parts. Thought signatures must
be replayed verbatim on subsequent turns to preserve the model's reasoning
state; third-party instrumentors typically drop them, which breaks
multi-turn tool flows.

This example demonstrates the canonical pattern:

  1. Instrument the SDK once at startup.
  2. Run a multi-turn conversation. On each turn, append the model's
     ``response.candidates[0].content`` to the history as-is — that
     ``Content`` object carries the thought_signature on its function-call
     parts.
  3. Subsequent ``generate_content`` calls automatically replay the
     signatures because they're embedded in the appended ``Content``.

Run with:
    export GEMINI_API_KEY=...
    uv run -m introspection_examples.otel.gemini_sdk.gemini_native
"""

from typing import Any, cast

try:
    from google import genai
    from google.genai import types
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: pip install google-genai"
    ) from e

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.otel.gemini import GeminiInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


def get_weather(city: str) -> dict:
    """Mock tool. Returns temperature in Celsius."""
    data = {
        "Tokyo": {"temperature_c": 25, "conditions": "Clear"},
        "Paris": {"temperature_c": 12, "conditions": "Rainy"},
    }
    return data.get(city, {"error": f"No data for {city}"})


def main() -> None:
    # --- 1. Instrument the SDK ----------------------------------------------
    provider = TracerProvider()
    provider.add_span_processor(
        IntrospectionSpanProcessor(service_name="gemini-native-example")
    )
    trace.set_tracer_provider(provider)

    instrumentor = GeminiInstrumentor()
    instrumentor.instrument(tracer_provider=provider)

    # --- 2. Set up the client and tools ------------------------------------
    client = genai.Client()
    model = "gemini-3-pro-preview"

    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_weather",
                description=(
                    "Get weather for a city. Returns conditions and "
                    "temperature in Celsius."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={"city": types.Schema(type=types.Type.STRING)},
                    required=["city"],
                ),
            )
        ]
    )
    config = types.GenerateContentConfig(
        tools=[tool],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    contents: list = [
        types.Content(
            role="user",
            parts=[types.Part(text="What's the weather in Tokyo?")],
        ),
    ]

    # --- 3. Turn 1: model thinks and calls the tool ------------------------
    print("=== Turn 1: Thinking + Tool Call ===")
    response1 = cast(
        Any,
        client.models.generate_content(
            model=model, contents=contents, config=config
        ),
    )
    for part in response1.candidates[0].content.parts:
        if part.thought:
            print(f"  [Thinking] {(part.text or '')[:80]}...")
        if part.function_call:
            print(
                f"  [Tool] {part.function_call.name}({dict(part.function_call.args)})"
            )

    # Append the model's content as-is — thought_signature lives on its parts
    # and MUST be sent back on subsequent turns to preserve reasoning state.
    contents.append(response1.candidates[0].content)

    fc = next(
        p.function_call
        for p in response1.candidates[0].content.parts
        if p.function_call
    )
    result = get_weather(dict(fc.args).get("city", ""))
    print(f"  [Result] {result}")

    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name=fc.name, response=result
                )
            ],
        )
    )

    # --- 4. Turn 2: model summarizes the tool result -----------------------
    print("\n=== Turn 2: Tool Result → Model Summarizes ===")
    response2 = cast(
        Any,
        client.models.generate_content(
            model=model, contents=contents, config=config
        ),
    )
    for part in response2.candidates[0].content.parts:
        if part.thought:
            print(f"  [Thinking] {(part.text or '')[:80]}...")
        elif part.text:
            print(f"  [Response] {part.text[:200]}")

    contents.append(response2.candidates[0].content)

    # --- 5. Turn 3: follow-up that requires reasoning over Turn 2 ----------
    print("\n=== Turn 3: Follow-up — model reasons over previous output ===")
    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        "What is that temperature in Fahrenheit? "
                        "And should I bring a jacket?"
                    )
                )
            ],
        )
    )
    response3 = cast(
        Any,
        client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=True),
            ),
        ),
    )
    for part in response3.candidates[0].content.parts:
        if part.thought:
            print(f"  [Thinking] {(part.text or '')[:80]}...")
        elif part.text:
            print(f"  [Response] {part.text[:200]}")

    instrumentor.uninstrument()
    print("\n✓ All turns completed. Thought signatures captured in traces.")


if __name__ == "__main__":
    main()
