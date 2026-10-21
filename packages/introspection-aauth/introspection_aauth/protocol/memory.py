"""What both servers' in-memory stores share."""

from typing import Any, Protocol, TypeVar


class Versioned(Protocol):
    @property
    def status(self) -> Any: ...

    @property
    def version(self) -> int: ...


Record = TypeVar("Record", bound=Versioned)


def compare_and_set(
    records: dict[Any, Record], key: Any, current: Record, changed: Record
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
