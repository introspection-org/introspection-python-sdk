"""Unit tests for provider-reported LLM cost extraction.

Covers :mod:`introspection_sdk.otel.usage` directly (pure helper, no
network) with OpenRouter-style usage payloads.
"""

from __future__ import annotations

from types import SimpleNamespace

from introspection_sdk.otel.usage import (
    UsageCostAttr,
    as_cost_float,
    usage_cost_attributes,
)

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
