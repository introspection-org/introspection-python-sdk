"""What both servers' in-memory stores share."""

from collections.abc import Hashable
from enum import StrEnum
from typing import Protocol, TypeVar


class Versioned(Protocol):
    @property
    def status(self) -> StrEnum: ...

    @property
    def version(self) -> int: ...


Record = TypeVar("Record", bound=Versioned)
Key = TypeVar("Key", bound=Hashable)


def compare_and_set(
    records: dict[Key, Record], key: Key, current: Record, changed: Record
) -> bool:
    """Replace `records[key]` with `changed` only if it still has `current`'s
    status and version: how a store refuses a write made on a stale read."""
    stored = records.get(key)
    if stored is None or (stored.status, stored.version) != (
        current.status,
        current.version,
    ):
        return False
    records[key] = changed
    return True
