"""Discriminators for response unions that decode a member added later."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["tag_or_unknown"]


def tag_or_unknown(field: str, known: frozenset[str]) -> Callable[[Any], str]:
    """A union discriminator on ``field``: a value outside ``known`` selects
    the union's ``unknown`` member, so a member the API adds later decodes."""

    def tag(payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get(field)
        else:
            value = getattr(payload, field, None)
        return value if value in known else "unknown"

    return tag
