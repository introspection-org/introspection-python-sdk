"""The contract check: this SDK's routes against both API references.

It fails when

1. an operation whose `x-introspection.clients` includes `sdk` has no call
   site in the SDK;
2. the SDK calls a `/v1/...` route (method and path) that is in neither
   reference.

Field-level changes in the API are oasdiff's to report, in the nightly
workflow; this check compares routes only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from api_contract.reference import CLIENT, operations
from api_contract.routes import discover
from api_contract.source import Package

__all__ = ["Result", "run"]

logger = logging.getLogger(__name__)


@dataclass
class Result:
    operations: int = 0
    uncalled: list[str] = field(default_factory=list)
    unknown_route: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.uncalled or self.unknown_route)

    def counts(self) -> str:
        return (
            f"{len(self.uncalled)} sdk operations never called, "
            f"{len(self.unknown_route)} routes in neither reference"
        )

    def render(self) -> str:
        sections = [
            f"{means}:" + "".join(f"\n      {item}" for item in items)
            for items, means in (
                (
                    self.uncalled,
                    "operations — flagged for the SDK in x-introspection but "
                    "no call site in introspection_sdk/ sends it",
                ),
                (
                    self.unknown_route,
                    "routes — called by this SDK but in neither API reference "
                    "(? means the call's method could not be read)",
                ),
            )
            if items
        ]
        sections.append(
            f"✗ SDK routes disagree with the API references ({self.counts()})"
            if self.failed
            else f"✓ SDK routes match the API references ({self.operations} "
            "operations)"
        )
        return "\n\n".join(sections)


def run(package: Package, specs: dict[str, dict[str, Any]]) -> Result:
    """`specs` maps a plane name (`controlplane`, `dataplane`) to its
    document."""
    ops = [
        op for plane, spec in specs.items() for op in operations(plane, spec)
    ]
    keys = {op.key for op in ops}
    called = set()
    result = Result(operations=len(ops))
    for site in discover(package):
        key = f"{site.method} {site.path}"
        if key in keys:
            called.add(key)
        else:
            result.unknown_route.append(f"{key} ({site.at})")
    result.uncalled = sorted(
        op.name for op in ops if CLIENT in op.clients and op.key not in called
    )
    result.unknown_route.sort()
    logger.info(
        "API contract checked",
        extra={"operations": result.operations, "failed": result.failed},
    )
    return result
