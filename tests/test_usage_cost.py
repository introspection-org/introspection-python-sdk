"""Unit tests for provider-reported LLM cost extraction.

Covers :mod:`introspection_sdk.otel._usage` directly (pure helper, no
network) plus the wired-in emission sites that can be driven with real
in-memory span exporters: the Anthropic response-attribute setter and
the OpenAI Agents generation-span processor path are covered by their
own test modules' payloads; here we exercise the shared helper and the
Anthropic non-streaming site with an OpenRouter-style usage payload.
"""

from __future__ import annotations

from types import SimpleNamespace

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from introspection_sdk.otel._usage import (
    UsageCostAttr,
    as_cost_float,
    set_usage_cost_attributes,
    usage_cost_attributes,
)
from introspection_sdk.otel.anthropic import _set_response_attrs

# --- usage_cost_attributes: present -----------------------------------


def test_dict_payload_all_fields_present():
    usage = {
        "prompt_tokens": 14,
        "completion_tokens": 163,
        "cost": 0.95,
        "cost_details": {"upstream_inference_cost": 0.5},
        "completion_tokens_details": {"reasoning_tokens": 128},
    }
    assert usage_cost_attributes(usage) == {
        UsageCostAttr.COST_USD: 0.95,
        UsageCostAttr.UPSTREAM_COST_USD: 0.5,
        UsageCostAttr.REASONING_TOKENS: 128,
    }


def test_object_payload_all_fields_present():
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=20,
        cost=1.25,
        cost_details=SimpleNamespace(upstream_inference_cost=1.0),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=64),
    )
    assert usage_cost_attributes(usage) == {
        UsageCostAttr.COST_USD: 1.25,
        UsageCostAttr.UPSTREAM_COST_USD: 1.0,
        UsageCostAttr.REASONING_TOKENS: 64,
    }


def test_int_cost_is_coerced_to_float():
    attrs = usage_cost_attributes({"cost": 2})
    assert attrs == {UsageCostAttr.COST_USD: 2.0}
    assert isinstance(attrs[UsageCostAttr.COST_USD], float)


def test_zero_cost_is_still_emitted():
    # Present-with-zero is a real provider report (free-tier routes),
    # distinct from absent.
    assert usage_cost_attributes({"cost": 0.0}) == {
        UsageCostAttr.COST_USD: 0.0
    }


# --- usage_cost_attributes: absent -------------------------------------


def test_absent_fields_emit_nothing():
    assert (
        usage_cost_attributes({"prompt_tokens": 14, "completion_tokens": 2})
        == {}
    )


def test_none_usage_emits_nothing():
    assert usage_cost_attributes(None) == {}


def test_partial_details_emit_only_present_fields():
    usage = {
        "cost": 0.95,
        "cost_details": {},
        "completion_tokens_details": {"audio_tokens": 3},
    }
    assert usage_cost_attributes(usage) == {UsageCostAttr.COST_USD: 0.95}


# --- usage_cost_attributes: malformed ----------------------------------


def test_non_numeric_cost_is_skipped():
    assert usage_cost_attributes({"cost": "0.95"}) == {}
    assert usage_cost_attributes({"cost": True}) == {}
    assert usage_cost_attributes({"cost": {"usd": 0.95}}) == {}


def test_malformed_nested_payloads_are_skipped():
    usage = {
        "cost_details": "not-a-dict",
        "completion_tokens_details": 42,
    }
    assert usage_cost_attributes(usage) == {}


def test_non_int_reasoning_tokens_are_skipped():
    assert (
        usage_cost_attributes(
            {"completion_tokens_details": {"reasoning_tokens": 12.5}}
        )
        == {}
    )
    assert (
        usage_cost_attributes(
            {"completion_tokens_details": {"reasoning_tokens": "many"}}
        )
        == {}
    )


def test_as_cost_float_rejects_non_numbers():
    assert as_cost_float(0.95) == 0.95
    assert as_cost_float(3) == 3.0
    assert as_cost_float(True) is None
    assert as_cost_float("0.95") is None
    assert as_cost_float(None) is None


# --- set_usage_cost_attributes / anthropic wiring -----------------------


def _make_span_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return tracer.start_span("chat"), exporter


def test_set_usage_cost_attributes_sets_only_present_fields():
    span, exporter = _make_span_and_exporter()
    set_usage_cost_attributes(span, {"cost": 0.95, "prompt_tokens": 1})
    span.end()

    (finished,) = exporter.get_finished_spans()
    attrs = dict(finished.attributes or {})
    assert attrs[UsageCostAttr.COST_USD] == 0.95
    assert UsageCostAttr.UPSTREAM_COST_USD not in attrs
    assert UsageCostAttr.REASONING_TOKENS not in attrs


def test_anthropic_response_attrs_include_provider_cost():
    span, exporter = _make_span_and_exporter()
    response = SimpleNamespace(
        id="msg_1",
        model="claude-test",
        content=[],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cost=0.95,
            cost_details=SimpleNamespace(upstream_inference_cost=0.5),
        ),
    )
    _set_response_attrs(span, response)
    span.end()

    (finished,) = exporter.get_finished_spans()
    attrs = dict(finished.attributes or {})
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5
    assert attrs[UsageCostAttr.COST_USD] == 0.95
    assert attrs[UsageCostAttr.UPSTREAM_COST_USD] == 0.5


def test_anthropic_response_attrs_without_cost_emit_no_cost_attrs():
    span, exporter = _make_span_and_exporter()
    response = SimpleNamespace(
        id="msg_2",
        model="claude-test",
        content=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    _set_response_attrs(span, response)
    span.end()

    (finished,) = exporter.get_finished_spans()
    attrs = dict(finished.attributes or {})
    assert UsageCostAttr.COST_USD not in attrs
    assert UsageCostAttr.UPSTREAM_COST_USD not in attrs
    assert UsageCostAttr.REASONING_TOKENS not in attrs
