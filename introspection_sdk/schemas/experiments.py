"""Pydantic mirrors of CP `/v1/experiments` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    CONCLUDED = "concluded"
    CANCELLED = "cancelled"


class Arm(_ApiModel):
    label: str
    recipe_id: UUID | None = None
    weight: float | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class Experiment(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    status: ExperimentStatus = ExperimentStatus.DRAFT
    arms: list[Arm] | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    winning_arm_label: str | None = None
    started_at: datetime | None = None
    concluded_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExperimentCreate(_ApiModel):
    project: str | UUID
    name: str
    arms: list[Arm] | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class ExperimentUpdate(_ApiModel):
    name: str | None = None
    arms: list[Arm] | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


__all__ = [
    "Arm",
    "Experiment",
    "ExperimentCreate",
    "ExperimentStatus",
    "ExperimentUpdate",
]
