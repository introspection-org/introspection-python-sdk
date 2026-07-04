"""Provider-reported LLM cost extraction shared by the instrumentors.

Some providers report the billed cost of a call directly in the
response ``usage`` block. OpenRouter, for example, returns::

    "usage": {
        "prompt_tokens": 14,
        "completion_tokens": 163,
        "cost": 0.95,
        "cost_details": {"upstream_inference_cost": 0.5},
        "completion_tokens_details": {"reasoning_tokens": 128}
    }

The helpers here lift those optional fields onto the LLM span so the
platform can use the provider-reported cost as the ceiling comparison
point against table pricing. Fields that are absent — or present but
non-numeric — are skipped silently: no attribute is emitted for them.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.trace import Span

__all__ = [
    "UsageCostAttr",
    "as_cost_float",
    "set_usage_cost_attributes",
    "usage_cost_attributes",
]


class UsageCostAttr:
    """Span attribute keys for provider-reported usage cost.

    Cost keys use a ``_usd`` suffix to align with the Claude Agent
    SDK's ``total_cost_usd`` result field.
    """

    COST_USD = "introspection.llm.cost_usd"
    """Provider-reported total cost in USD (``usage.cost``)."""

    UPSTREAM_COST_USD = "introspection.llm.upstream_cost_usd"
    """Upstream inference cost in USD
    (``usage.cost_details.upstream_inference_cost``)."""

    REASONING_TOKENS = "gen_ai.usage.reasoning_tokens"
    """Reasoning tokens included in the output
    (``usage.completion_tokens_details.reasoning_tokens``)."""


def _get(obj: Any, key: str) -> Any:
    """Read ``key`` from a dict-style or attribute-style usage payload."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def as_cost_float(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` if it is not a real number.

    Rejects bools (which are ``int`` subclasses) and any non-numeric
    type so malformed payloads are skipped rather than raised on.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _as_int(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` if it is not an int."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def usage_cost_attributes(usage: Any) -> dict[str, float | int]:
    """Extract provider-reported cost attributes from a usage payload.

    Accepts both dict payloads and SDK usage objects (attribute
    access). Returns a dict keyed by :class:`UsageCostAttr` values
    containing only the fields that are present and numeric in
    ``usage`` — absent or malformed fields contribute nothing.

    Args:
        usage: The response ``usage`` block (dict, object, or ``None``).

    Returns:
        Attribute dict ready to be set on the LLM span.
    """
    attrs: dict[str, float | int] = {}
    if usage is None:
        return attrs

    cost = as_cost_float(_get(usage, "cost"))
    if cost is not None:
        attrs[UsageCostAttr.COST_USD] = cost

    cost_details = _get(usage, "cost_details")
    if cost_details is not None:
        upstream = as_cost_float(_get(cost_details, "upstream_inference_cost"))
        if upstream is not None:
            attrs[UsageCostAttr.UPSTREAM_COST_USD] = upstream

    completion_details = _get(usage, "completion_tokens_details")
    if completion_details is not None:
        reasoning = _as_int(_get(completion_details, "reasoning_tokens"))
        if reasoning is not None:
            attrs[UsageCostAttr.REASONING_TOKENS] = reasoning

    return attrs


def set_usage_cost_attributes(span: Span, usage: Any) -> None:
    """Set provider-reported cost attributes on ``span`` when present.

    Args:
        span: The LLM span to annotate.
        usage: The response ``usage`` block (dict, object, or ``None``).
    """
    for key, value in usage_cost_attributes(usage).items():
        span.set_attribute(key, value)
