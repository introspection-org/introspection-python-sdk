"""Contract tests for the read-only ``runner.metrics`` namespace.

Covers the ``POST /v1/metrics`` request body serialization and the typed
response parse, driven through the offline :class:`FakeAPI` transport.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from introspection_sdk.runner_resources import AsyncMetrics, Metrics
from introspection_sdk.schemas.metrics import (
    MetricQueryRequest,
    MetricSpec,
)

from .conftest import FakeAPI

RESPONSE_FIXTURE: dict[str, Any] = {
    "data": [
        {
            "timestamp": None,
            "dimensions": [{"field": "service_name", "value": "agent"}],
            "metrics": [
                {
                    "metric_index": 0,
                    "measure": None,
                    "aggregation": "count",
                    "value": 42.0,
                }
            ],
        }
    ],
    "meta": {
        "view": "conversations",
        "window": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        "row_count": 1,
        "row_limit": 100,
    },
}


def _request() -> MetricQueryRequest:
    return MetricQueryRequest(
        view="conversations",
        metrics=[MetricSpec(aggregation="count")],
        from_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        to_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
    )


def test_query_posts_body_and_parses_response(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/metrics", json_body=RESPONSE_FIXTURE)
    metrics = Metrics(fake_api.client())

    result = metrics.query(_request())

    req = fake_api.last_request
    assert req.method == "POST"
    assert req.path == "/v1/metrics"
    body = req.json()
    assert body["view"] == "conversations"
    assert body["metrics"] == [{"aggregation": "count"}]
    assert body["from_timestamp"].startswith("2025-01-01")

    assert result.meta.view == "conversations"
    assert result.data[0].metrics[0].value == 42.0


def test_query_accepts_raw_dict(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/metrics", json_body=RESPONSE_FIXTURE)
    metrics = Metrics(fake_api.client())

    result = metrics.query(
        {
            "view": "conversations",
            "metrics": [{"aggregation": "count"}],
            "from_timestamp": "2025-01-01T00:00:00Z",
            "to_timestamp": "2025-01-02T00:00:00Z",
        }
    )

    assert result.data[0].dimensions[0].field == "service_name"


def test_metric_spec_requires_measure_for_non_count():
    # A non-count op requires a measure; count must not carry one. The request
    # model mirrors the DP's closed contract, so misuse fails locally.
    with pytest.raises(ValueError):
        MetricSpec(aggregation="avg")
    with pytest.raises(ValueError):
        MetricSpec(aggregation="count", measure="duration_ms")


def test_request_rejects_unknown_fields():
    # extra="forbid" mirrors the DP: a misspelled option must fail, not run a
    # different query silently.
    with pytest.raises(ValueError):
        MetricQueryRequest.model_validate(
            {
                "view": "spans",
                "metrics": [{"aggregation": "count"}],
                "from_timestamp": "2025-01-01T00:00:00Z",
                "to_timestamp": "2025-01-02T00:00:00Z",
                "unknown_field": True,
            }
        )


async def test_async_query(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/metrics", json_body=RESPONSE_FIXTURE)
    metrics = AsyncMetrics(fake_api.async_client())

    result = await metrics.query(_request())

    assert result.meta.row_count == 1
