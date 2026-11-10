"""Cursor pagination envelope shared by every DP list endpoint."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    """One page of a list read; a field the API adds is ignored."""

    records: list[T]
    count: int
    total_count: int | None = None
    next: str | None = None
