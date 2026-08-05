"""The GenAI span — the object ``/v1/conversations`` returns.

These are pure-unit tests of a serialization contract, so no cassettes: nothing
here crosses a process or network boundary, and the thing under test *is* the
shape.

Two properties carry most of the weight, because they are the two the flat
representation got wrong (see `conversations-genai-representation.md` §1):

- **Nothing serializes as null.** An absent value is an absent key.
- **Nothing is dropped.** The attribute tree is open, so an attribute no model
  declared still arrives and still round-trips.
"""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk.schemas.genai_span import GenAiSpan, GenAiSpanList


def _nulls(value: Any, path: str = "") -> list[str]:
    """Every path in a serialized payload whose value is ``None``."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if child is None:
                found.append(f"{path}.{key}")
            else:
                found.extend(_nulls(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_nulls(child, f"{path}[{index}]"))
    return found


FULL_SPAN: dict[str, Any] = {
    "trace_id": "8f0efe5966587e51364046b44b5d0029",
    "span_id": "caa8ff6f77084ded",
    "parent_span_id": "623224d3c1b1a99b",
    "name": "chat claude-sonnet-4-6",
    "kind": "INTERNAL",
    "start_time": "2026-08-04T22:14:34.506000Z",
    "end_time": "2026-08-04T22:14:37.482470Z",
    "duration_ns": 2976470577,
    "status": {"code": "Unset"},
    "resource": {"service": {"name": "coding-agent"}},
    "attributes": {
        "gen_ai": {
            "operation": {"name": "chat"},
            "provider": {"name": "anthropic"},
            "conversation": {"id": "019fcee7-4fcc-7793-a1ce-8047b3518303"},
            "agent": {"id": "agent:019fced4", "name": "agent"},
            "request": {"model": "claude-sonnet-4-6"},
            "response": {"model": "claude-sonnet-4-6", "id": "msg_011Cdi"},
            "usage": {
                "input_tokens": 1527,
                "output_tokens": 45,
                "cache_creation": {"input_tokens": 1524},
            },
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "parts": [{"type": "text", "content": "hey"}],
                    }
                ]
            },
            "output": {
                "messages": [
                    {
                        "role": "assistant",
                        "parts": [{"type": "text", "content": "hi"}],
                        "finish_reason": "stop",
                    }
                ]
            },
        },
        "introspection": {
            "member": {"id": "019fbe0c"},
            "environment": "production",
            "conversation": {"position": 1, "is_new": True},
        },
    },
}


class TestSemconvNaming:
    """Attributes keep the names the span was written with."""

    def test_the_tree_is_addressed_by_convention_name(self) -> None:
        # The whole point: a reader who knows the semantic conventions can
        # find a value without learning a private dialect for it.
        span = GenAiSpan.model_validate(FULL_SPAN)

        assert span.attributes.gen_ai.operation.name == "chat"
        assert span.attributes.gen_ai.provider.name == "anthropic"
        assert span.attributes.gen_ai.request.model == "claude-sonnet-4-6"
        assert span.attributes.gen_ai.usage.input_tokens == 1527

    def test_cache_tokens_nest_the_way_the_convention_nests_them(self) -> None:
        # `gen_ai.usage.cache_read.input_tokens` is a nested count, not a flat
        # `cache_read_input_tokens` — this was our local extension before the
        # conventions adopted it, and the nesting is the adopted spelling.
        span = GenAiSpan.model_validate(FULL_SPAN)

        assert span.attributes.gen_ai.usage.cache_creation.input_tokens == 1524

    def test_introspection_attributes_sit_beside_gen_ai_not_inside_it(
        self,
    ) -> None:
        span = GenAiSpan.model_validate(FULL_SPAN)

        assert span.attributes.introspection.member.id == "019fbe0c"
        assert span.attributes.introspection.environment == "production"


class TestNullIsNeverSerialized:
    def test_a_fully_populated_span_serializes_no_nulls(self) -> None:
        dumped = GenAiSpan.model_validate(FULL_SPAN).model_dump(mode="json")

        assert _nulls(dumped) == []

    def test_a_minimal_span_serializes_no_nulls(self) -> None:
        # The case that matters more: most spans are mostly empty, and the flat
        # representation rendered that emptiness as ~30 explicit nulls.
        span = GenAiSpan.model_validate(
            {"trace_id": "t", "start_time": "2026-08-04T22:14:34Z"}
        )

        assert _nulls(span.model_dump(mode="json")) == []

    def test_absent_optional_fields_are_absent_keys_not_null_values(
        self,
    ) -> None:
        dumped = GenAiSpan.model_validate(
            {"trace_id": "t", "start_time": "2026-08-04T22:14:34Z"}
        ).model_dump(mode="json")

        assert "parent_span_id" not in dumped
        assert "end_time" not in dumped
        assert "status" not in dumped

    def test_message_parts_omit_their_own_nulls_too(self) -> None:
        # The leak that is easy to miss: the envelope can omit nulls perfectly
        # while the message models nested four levels down still emit theirs.
        dumped = GenAiSpan.model_validate(FULL_SPAN).model_dump(mode="json")
        message = dumped["attributes"]["gen_ai"]["input"]["messages"][0]

        assert "name" not in message

    def test_a_real_zero_is_kept(self) -> None:
        # Omitting nulls must not become omitting falsey values: a turn that
        # genuinely produced no output tokens is a fact, not an absence.
        span = GenAiSpan.model_validate(
            {
                "trace_id": "t",
                "start_time": "2026-08-04T22:14:34Z",
                "attributes": {"gen_ai": {"usage": {"output_tokens": 0}}},
            }
        )

        assert span.model_dump(mode="json")["attributes"]["gen_ai"][
            "usage"
        ] == {"output_tokens": 0}


class TestTheTreeIsOpen:
    def test_an_undeclared_gen_ai_attribute_survives(self) -> None:
        # The lossiness fix. A customer attribute nobody modelled must arrive,
        # or this representation has the same defect as the one it replaces.
        span = GenAiSpan.model_validate(
            {
                "trace_id": "t",
                "start_time": "2026-08-04T22:14:34Z",
                "attributes": {
                    "gen_ai": {"vendor_specific": {"nested": "kept"}}
                },
            }
        )

        assert span.attributes.gen_ai.model_extra["vendor_specific"] == {
            "nested": "kept"
        }

    def test_an_entirely_unknown_attribute_family_survives(self) -> None:
        span = GenAiSpan.model_validate(
            {
                "trace_id": "t",
                "start_time": "2026-08-04T22:14:34Z",
                "attributes": {"acme": {"tenant": "x"}},
            }
        )

        assert span.attributes.model_extra["acme"] == {"tenant": "x"}

    def test_unknown_attributes_round_trip_through_serialization(self) -> None:
        # Surviving validation is not enough — it has to come back out.
        raw = {
            "trace_id": "t",
            "start_time": "2026-08-04T22:14:34Z",
            "attributes": {
                "gen_ai": {"vendor_specific": "kept"},
                "acme": {"a": 1},
            },
        }

        dumped = GenAiSpan.model_validate(raw).model_dump(mode="json")

        assert dumped["attributes"]["gen_ai"]["vendor_specific"] == "kept"
        assert dumped["attributes"]["acme"] == {"a": 1}


class TestConvenienceAccessors:
    def test_messages_are_reachable_without_walking_the_tree(self) -> None:
        span = GenAiSpan.model_validate(FULL_SPAN)

        assert span.conversation_id == "019fcee7-4fcc-7793-a1ce-8047b3518303"
        assert span.input_messages[0].role == "user"
        assert span.output_messages[0].finish_reason == "stop"

    def test_accessors_return_empty_rather_than_raising_on_a_bare_span(
        self,
    ) -> None:
        # A tool span carries no messages at all; reaching for them is normal
        # and must not require four levels of None-checking at the call site.
        span = GenAiSpan.model_validate(
            {"trace_id": "t", "start_time": "2026-08-04T22:14:34Z"}
        )

        assert span.input_messages == []
        assert span.output_messages == []
        assert span.conversation_id is None


class TestOneShapeTwoDepths:
    """List and items return the same type; only message depth differs."""

    @pytest.mark.parametrize("message_count", [1, 12])
    def test_the_same_model_parses_a_preview_and_a_full_history(
        self, message_count: int
    ) -> None:
        # The list read sends one message; the items read sends the whole
        # conversation so it can be resumed. Same type either way — if this
        # ever needed two models, the "one parser" claim would be false.
        raw = {
            "trace_id": "t",
            "start_time": "2026-08-04T22:14:34Z",
            "attributes": {
                "gen_ai": {
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "parts": [
                                    {"type": "text", "content": f"m{i}"}
                                ],
                            }
                            for i in range(message_count)
                        ]
                    }
                }
            },
        }

        span = GenAiSpan.model_validate(raw)

        assert len(span.input_messages) == message_count

    def test_the_list_envelope_keeps_cursor_pagination(self) -> None:
        page = GenAiSpanList.model_validate(
            {
                "object": "list",
                "data": [FULL_SPAN],
                "first_id": "caa8ff6f77084ded",
                "has_more": True,
                "next": "cursor-abc",
            }
        )

        assert page.has_more is True
        assert page.next == "cursor-abc"
        assert page.data[0].attributes.gen_ai.operation.name == "chat"

    def test_an_empty_page_is_valid_and_serializes_no_nulls(self) -> None:
        page = GenAiSpanList.model_validate({"object": "list", "data": []})

        assert page.data == []
        assert _nulls(page.model_dump(mode="json")) == []
