"""Message-part parsing — what a reader does with a part it did not expect.

Before this, `MessagePart` was a strictly discriminated union over the five
part types this SDK modelled. That meant an unmodelled part did not degrade: it
raised `union_tag_invalid`, and Pydantic raises for the *message*, not the part.
A single image in a conversation made the whole message unparseable, and every
message in the turn with it.

Two things are being pinned here:

- **An unknown part is not an error.** The platform can write a type this build
  has never heard of — a newer part type, a provider-specific one, one added to
  the spec after release. It has to arrive as "some part, contents preserved".
- **A part type has aliases, permanently.** `thinking` is the canonical name and
  the one the platform writes; the semantic conventions spell it `reasoning`.
  Both parse. This is not a transition with an end: telemetry is append-only, so
  a part type is *stored bytes*, and spans written with either spelling stay
  readable for as long as they exist. That is the opposite of the conversations
  envelope, which is computed on read and could be cut over cleanly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from introspection_sdk.schemas.genai import (
    BinaryPart,
    CompactionPart,
    FilePart,
    GenericPart,
    InputMessage,
    MessagePart,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
    UrlPart,
)

PART = TypeAdapter(MessagePart)


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        ({"type": "text", "content": "hi"}, TextPart),
        ({"type": "thinking", "content": "hm"}, ThinkingPart),
        ({"type": "reasoning", "content": "hm"}, ThinkingPart),
        ({"type": "tool_call", "name": "search"}, ToolCallRequestPart),
        (
            {"type": "tool_call_response", "response": "ok"},
            ToolCallResponsePart,
        ),
        ({"type": "binary", "media_type": "image/png"}, BinaryPart),
        ({"type": "blob", "mime_type": "image/png"}, BinaryPart),
        ({"type": "image-url", "url": "https://e.test/a.png"}, UrlPart),
        ({"type": "audio-url", "url": "https://e.test/a.mp3"}, UrlPart),
        ({"type": "video-url", "url": "https://e.test/a.mp4"}, UrlPart),
        ({"type": "document-url", "url": "https://e.test/a.pdf"}, UrlPart),
        ({"type": "uri", "uri": "https://e.test/a.png"}, UrlPart),
        ({"type": "file", "file_id": "file-1"}, FilePart),
        ({"type": "compaction", "content": "summary"}, CompactionPart),
    ],
)
def test_every_written_part_type_parses(
    payload: dict[str, Any], model: type
) -> None:
    """Each type the platform writes, plus each spec spelling, finds a model."""
    assert isinstance(PART.validate_python(payload), model)


def test_unknown_part_degrades_instead_of_failing_the_message() -> None:
    """A part nobody modelled arrives intact rather than taking the message down.

    The failure mode this replaces was not "the part is missing" — it was a
    `ValidationError` for the enclosing message, so the user saw nothing at all.
    """
    message = InputMessage.model_validate(
        {
            "role": "user",
            "parts": [
                {"type": "text", "content": "look at this"},
                {"type": "holographic-projection", "payload": {"depth": 3}},
            ],
        }
    )

    text, unknown = message.parts
    assert isinstance(text, TextPart)
    assert isinstance(unknown, GenericPart)
    assert unknown.type == "holographic-projection"
    # Contents survive, so a renderer can still show *something* and a round
    # trip through the SDK is not lossy.
    assert unknown.model_dump()["payload"] == {"depth": 3}


def test_thinking_and_reasoning_are_the_same_part() -> None:
    """Both spellings parse, and each keeps the spelling it was written with.

    Normalizing `reasoning` to `thinking` on the way in would be rewriting what
    the span says. The reader collapses the two; the record does not.
    """
    canonical = PART.validate_python(
        {"type": "thinking", "content": "a", "redacted": True}
    )
    spec = PART.validate_python({"type": "reasoning", "content": "a"})

    assert isinstance(canonical, ThinkingPart) and isinstance(
        spec, ThinkingPart
    )
    assert canonical.type == "thinking"
    assert spec.type == "reasoning"
    assert canonical.redacted is True


def test_url_part_exposes_either_spelling_of_its_target() -> None:
    """`url` and the spec's `uri` are one location, reachable one way."""
    legacy = PART.validate_python(
        {"type": "image-url", "url": "https://e.test/a.png"}
    )
    spec = PART.validate_python(
        {"type": "uri", "uri": "https://e.test/a.png", "modality": "image"}
    )

    assert isinstance(legacy, UrlPart) and isinstance(spec, UrlPart)
    assert legacy.target == spec.target == "https://e.test/a.png"


def test_parts_do_not_serialize_absent_fields_as_null() -> None:
    """A part carries only what it has — the same rule as the span envelope."""
    dumped = PART.validate_python(
        {"type": "thinking", "content": "a"}
    ).model_dump()

    assert dumped == {"type": "thinking", "content": "a"}


def test_thinking_replay_fields_survive_a_round_trip() -> None:
    """The signature and provider are what make a thinking block replayable.

    They are the reason this part is not just text, so losing them silently on
    a round trip would be worse than failing to parse.
    """
    payload = {
        "type": "thinking",
        "content": "summary",
        "signature": "sig-abc",
        "provider_name": "anthropic",
        "redacted": True,
    }

    assert PART.validate_python(payload).model_dump() == payload
