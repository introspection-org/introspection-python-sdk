"""Pydantic mirrors of CP `/v1/experiments` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"``.

An experiment routes traffic across 2-20 *arms* (runtime versions sharing
one runtime group) and optimizes a judge-backed *goal*. Prerequisites, in
order: a recipe repository with at least one ``judges/*.yaml``; a runtime
versioned from it (judge sync populates ``GET /v1/judges``); further runtime
versions in the same group to use as arms. ``create`` produces a DRAFT that
routes nothing until ``start``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    ENDED = "ended"
    CANCELLED = "cancelled"


class ExperimentGoalDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class ExperimentGoalGuard(_ApiModel):
    """Canary bound over one component's rate."""

    min: float | None = None
    max: float | None = None


class JudgeGoalComponent(_ApiModel):
    """Judge-backed reward component.

    ``judge_id`` comes from ``GET /v1/judges`` — judges cannot be created via
    the API; author a ``judges/*.yaml`` in the recipe repository and it syncs
    when a runtime versions that commit.
    """

    source: Literal["judge"] = "judge"
    judge_id: UUID
    judge_definition_hash: str | None = None
    weight: float = 1.0
    guard: ExperimentGoalGuard | None = None


class TelemetryGoalComponent(_ApiModel):
    """Reserved shape for future telemetry-backed reward components."""

    source: Literal["telemetry"] = "telemetry"
    column: str | None = None
    aggregation: str | None = None
    weight: float = 1.0
    guard: ExperimentGoalGuard | None = None


ExperimentGoalComponent = JudgeGoalComponent | TelemetryGoalComponent


class ExperimentGoal(_ApiModel):
    """Composite objective the bandit optimizes.

    Create requires at least one ``source="judge"`` component with
    ``weight > 0`` — the v1 scorer only implements judge-backed reward.
    """

    kind: Literal["composite"] = "composite"
    direction: ExperimentGoalDirection = ExperimentGoalDirection.MAXIMIZE
    components: list[ExperimentGoalComponent] = Field(default_factory=list)


class ExperimentArmCreate(_ApiModel):
    """One arm in the create body — a runtime version + display label."""

    runtime_id: UUID
    arm_label: str
    agent_overrides: dict[str, str] | None = None


class ExperimentArm(_ApiModel):
    """One arm as returned on the experiment row."""

    runtime_id: UUID
    arm_label: str
    agent_overrides: dict[str, str] | None = None


class Experiment(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    runtime_group_id: UUID | None = None
    environment: str | None = None
    status: ExperimentStatus = ExperimentStatus.DRAFT
    routing_strategy: str | None = None
    arms: list[ExperimentArm] = Field(default_factory=list)
    goal_json: ExperimentGoal | None = None
    scoring_interval_seconds: int | None = None
    hash_key_fields: list[str] | None = None
    sample_rate: float | None = None
    description: str | None = None
    posterior_json: dict[str, Any] | None = None
    weights_json: dict[str, int] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    halted_at: datetime | None = None
    halted_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExperimentCreate(_ApiModel):
    """POST /v1/experiments body. Creates a DRAFT; call ``start`` to route."""

    project: str | UUID
    name: str
    runtime_group_id: UUID
    arms: list[ExperimentArmCreate] = Field(min_length=2, max_length=20)
    goal_json: ExperimentGoal
    description: str | None = None
    environment: str | None = None
    scoring_interval_seconds: int | None = None
    hash_key_fields: list[str] | None = None
    sample_rate: float | None = None


class ExperimentUpdate(_ApiModel):
    """PATCH /v1/experiments/{id}. Status transitions use start/end/cancel;
    runtime_group_id and arms are immutable once running."""

    name: str | None = None
    description: str | None = None
    goal_json: ExperimentGoal | None = None
    scoring_interval_seconds: int | None = None
    hash_key_fields: list[str] | None = None
    sample_rate: float | None = None


__all__ = [
    "Experiment",
    "ExperimentArm",
    "ExperimentArmCreate",
    "ExperimentCreate",
    "ExperimentGoal",
    "ExperimentGoalComponent",
    "ExperimentGoalDirection",
    "ExperimentGoalGuard",
    "ExperimentStatus",
    "ExperimentUpdate",
    "JudgeGoalComponent",
    "TelemetryGoalComponent",
]
