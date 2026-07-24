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

from introspection_sdk.schemas.runner import RunCaller, RunnerIdentity
from introspection_sdk.schemas.runtimes import RuntimeEnvironment


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    ENDED = "ended"
    CANCELLED = "cancelled"


class ExperimentRoutingStrategy(StrEnum):
    BETA_SAMPLE = "beta_sample"


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

    id: UUID
    runtime_id: UUID
    arm_label: str
    agent_overrides: dict[str, str] | None = None
    initial_weight: int


class Experiment(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    runtime_group_id: UUID
    environment: RuntimeEnvironment = "production"
    status: ExperimentStatus = ExperimentStatus.DRAFT
    routing_strategy: ExperimentRoutingStrategy = (
        ExperimentRoutingStrategy.BETA_SAMPLE
    )
    arms: list[ExperimentArm] = Field(default_factory=list)
    goal_json: ExperimentGoal
    scoring_interval_seconds: int = 300
    hash_key_fields: list[str] = Field(
        default_factory=lambda: [
            "user.id",
            "anonymous.id",
            "conversation.id",
        ]
    )
    sample_rate: float = 1.0
    description: str | None = None
    posterior_json: dict[str, Any] | None = None
    weights_json: dict[str, int] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    halted_at: datetime | None = None
    halted_reason: str | None = None
    created_by_member_id: UUID
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExperimentCreate(_ApiModel):
    """POST /v1/experiments body. Creates a DRAFT; call ``start`` to route."""

    project: str | UUID
    name: str
    runtime: str | UUID
    arms: list[ExperimentArmCreate] = Field(min_length=2, max_length=20)
    goal_json: ExperimentGoal
    description: str | None = None
    environment: RuntimeEnvironment | None = None
    scoring_interval_seconds: int | None = None
    hash_key_fields: list[str] | None = None
    sample_rate: float | None = None


class ExperimentUpdate(_ApiModel):
    """PATCH /v1/experiments/{id}. Status transitions use start/end/cancel;
    The selected Runtime and arms are immutable once running."""

    name: str | None = None
    description: str | None = None
    goal_json: ExperimentGoal | None = None
    scoring_interval_seconds: int | None = None
    hash_key_fields: list[str] | None = None
    sample_rate: float | None = None


class ExperimentRunRequest(_ApiModel):
    """Options accepted by ``POST /v1/experiments/{id}/run``.

    The Experiment owns its environment, so no environment selector is
    accepted. ``project`` is serialized as the route query parameter.
    """

    project: str | UUID | None = None
    identity: RunnerIdentity | None = None
    caller: RunCaller | None = None
    agent_name: str | None = None
    ttl_seconds: int | None = None
    scope: str | None = None
    bindings_required: bool | None = None


__all__ = [
    "Experiment",
    "ExperimentArm",
    "ExperimentArmCreate",
    "ExperimentCreate",
    "ExperimentGoal",
    "ExperimentGoalComponent",
    "ExperimentGoalDirection",
    "ExperimentGoalGuard",
    "ExperimentRoutingStrategy",
    "ExperimentRunRequest",
    "ExperimentStatus",
    "ExperimentUpdate",
    "JudgeGoalComponent",
    "TelemetryGoalComponent",
]
