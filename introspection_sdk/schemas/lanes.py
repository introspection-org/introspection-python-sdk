"""The deployment lane a Control Plane resource applies to."""

from __future__ import annotations

from enum import StrEnum


class Environment(StrEnum):
    """A lane: what an API key, Application, credential or variable is
    scoped to (wire field ``environment``)."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


__all__ = ["Environment"]
