"""The deployment lane a Control Plane resource applies to."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field


class Environment(StrEnum):
    """A lane: what an API key, Application, credential or variable is
    scoped to (wire field ``environment``)."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


OpenEnvironment = Annotated[
    Environment | str, Field(union_mode="left_to_right")
]


__all__ = ["Environment", "OpenEnvironment"]
