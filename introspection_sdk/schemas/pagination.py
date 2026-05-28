"""Cursor pagination envelope shared by every DP list endpoint."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="allow")

    records: list[T]
    count: int
    total_count: int | None = None
    next: str | None = None
