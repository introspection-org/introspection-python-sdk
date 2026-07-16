"""Pydantic mirrors of the DP bounded ``POST /v1/metrics`` contract.

The Metrics API is a deliberately closed, allow-listed "parameterized
report", not a query language: closed op/field allow-lists, an enum
interval, and hard caps (see the DP ``docs/design/metrics-api.md``). These
models mirror the request grammar and response envelope so callers can
build a typed request and read a typed result.

Field names are kept on-the-wire (snake_case) to match the DP models.
Request models set ``extra="forbid"`` — matching the DP — so a misspelled
option fails locally instead of silently running a different query.
Response models set ``extra="allow"`` so new server fields don't break
older clients.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AggInterval",
    "AggOp",
    "EffectiveWindow",
    "FilterOp",
    "MetricDimension",
    "MetricDimensionValue",
    "MetricFilter",
    "MetricHaving",
    "MetricOrderBy",
    "MetricOrderDirection",
    "MetricOrderType",
    "MetricQueryConfig",
    "MetricQueryMeta",
    "MetricQueryRequest",
    "MetricQueryResponse",
    "MetricResultRow",
    "MetricResultValue",
    "MetricSpec",
    "MetricTimeDimension",
    "MetricView",
]

AggOp = Literal[
    "count",
    "count_distinct",
    "sum",
    "avg",
    "min",
    "max",
    "p50",
    "p75",
    "p90",
    "p95",
    "p99",
]
"""Aggregation operators. ``count_distinct`` is cardinality (count of
distinct values of a field), not row count."""

FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "in", "nin", "exists", "contains"
]
"""Filter predicate operators."""

AggInterval = Literal[
    "10s",
    "30s",
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "3h",
    "6h",
    "12h",
    "1d",
    "2d",
    "1w",
    "1mo",
]
"""Fixed time-bucket widths (timeseries only)."""

MetricView = Literal[
    "spans",
    "conversations",
    "events",
    "judgements",
    "observations",
    "patterns",
]
"""The telemetry view a metrics query runs against."""

MetricOrderType = Literal["metric", "dimension", "time"]
MetricOrderDirection = Literal["asc", "desc"]
MetricHavingOperator = Literal["eq", "neq", "gt", "gte", "lt", "lte"]


class _RequestModel(BaseModel):
    # Matches the DP contract: unknown fields are rejected, not ignored.
    model_config = ConfigDict(extra="forbid")


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class MetricSpec(_RequestModel):
    """One aggregation: ``aggregation`` over an optional allow-listed
    numeric ``measure``. ``count`` takes no measure; every other op
    requires one."""

    aggregation: AggOp
    measure: str | None = None

    @model_validator(mode="after")
    def _validate_measure(self) -> MetricSpec:
        if self.aggregation == "count" and self.measure is not None:
            raise ValueError("count does not take a measure")
        if self.aggregation != "count" and not self.measure:
            raise ValueError(f"{self.aggregation} requires a measure")
        return self


class MetricDimension(_RequestModel):
    """One group-by dimension."""

    field: str


class MetricFilter(_RequestModel):
    """One filter predicate over an allow-listed field. ``value`` is a
    scalar for comparison ops, a list for ``in``/``nin``, and omitted for
    ``exists``."""

    field: str
    operator: FilterOp
    value: str | int | float | bool | list[str | int | float | bool] | None = (
        None
    )


class MetricTimeDimension(_RequestModel):
    """Time bucketing. Supply ``granularity`` (a fixed width or ``auto``)
    or ``bins`` (a bucket count)."""

    granularity: AggInterval | Literal["auto"] | None = None
    bins: int | None = None


class MetricOrderBy(_RequestModel):
    """One ordering directive. ``metric`` ordering targets ``metric_index``;
    ``dimension`` ordering targets ``field``; ``time`` ordering takes
    neither."""

    type: MetricOrderType
    direction: MetricOrderDirection = "asc"
    metric_index: int | None = None
    field: str | None = None


class MetricHaving(_RequestModel):
    """A post-aggregation threshold on one metric's value."""

    metric_index: int
    operator: MetricHavingOperator
    value: float


class MetricQueryConfig(_RequestModel):
    """Result-shaping caps."""

    row_limit: int = 100
    series_limit: int | None = None


class MetricQueryRequest(_RequestModel):
    """The full ``POST /v1/metrics`` request body."""

    view: MetricView
    metrics: list[MetricSpec]
    from_timestamp: datetime
    to_timestamp: datetime
    dimensions: list[MetricDimension] = Field(default_factory=list)
    filters: list[MetricFilter] = Field(default_factory=list)
    time_dimension: MetricTimeDimension | None = None
    order_by: list[MetricOrderBy] = Field(default_factory=list)
    having: list[MetricHaving] = Field(default_factory=list)
    config: MetricQueryConfig = Field(default_factory=MetricQueryConfig)


class EffectiveWindow(_ResponseModel):
    """The time window actually applied (default-filled when omitted)."""

    start: datetime
    end: datetime


class MetricDimensionValue(_ResponseModel):
    field: str
    value: str


class MetricResultValue(_ResponseModel):
    metric_index: int
    measure: str | None = None
    aggregation: AggOp
    value: float


class MetricResultRow(_ResponseModel):
    timestamp: int | None = None
    dimensions: list[MetricDimensionValue] = Field(default_factory=list)
    metrics: list[MetricResultValue] = Field(default_factory=list)


class MetricQueryMeta(_ResponseModel):
    view: MetricView
    window: EffectiveWindow
    row_count: int
    row_limit: int
    interval: AggInterval | None = None
    step_seconds: int | None = None
    approximate: bool = False
    truncated: bool = False
    order_by: list[MetricOrderBy] = Field(default_factory=list)


class MetricQueryResponse(_ResponseModel):
    """The ``POST /v1/metrics`` response envelope."""

    data: list[MetricResultRow] = Field(default_factory=list)
    meta: MetricQueryMeta
