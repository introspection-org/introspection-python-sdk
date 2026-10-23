"""The contract check: this SDK's routes against both API references.

It finds

1. operations for the SDK (no `x-introspection`, or one whose `clients`
   includes `sdk`) that have no call site in the SDK;
2. `/v1/...` routes (method and path) the SDK calls that are in neither
   reference.

The full check fails on both. A pull request fails only on the second,
which is the SDK's own fault: a route the cloud adds for the SDK must not
block an unrelated PR, so the first is only reported there.
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

    def failed(self, *, full: bool = True) -> bool:
        return bool(self.unknown_route or (full and self.uncalled))

    def counts(self) -> str:
        return (
            f"{len(self.uncalled)} sdk operations never called, "
            f"{len(self.unknown_route)} routes in neither reference"
        )

    def render(self, *, full: bool = True) -> str:
        sections = [
            f"{means}:" + "".join(f"\n      {item}" for item in items)
            for items, means in (
                (
                    self.uncalled,
                    "operations — for the SDK by x-introspection but "
                    "no call site in introspection_sdk/ sends it"
                    + ("" if full else " (reported only, never fails a PR)"),
                ),
                (
                    self.unknown_route,
                    "routes — called by this SDK but in neither API reference "
                    "(? means the call's method could not be read)",
                ),
            )
            if items
        ]
        if self.failed(full=full):
            verdict = "✗ SDK routes disagree with the API references"
        elif self.uncalled:
            verdict = "✓ every route this SDK calls is in the API references"
        else:
            verdict = "✓ SDK routes match the API references"
        sections.append(f"{verdict} ({self.counts()})")
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
        op.name for op in ops if op.wanted_by(CLIENT) and op.key not in called
    )
    result.unknown_route.sort()
    logger.info(
        "API contract checked",
        extra={
            "operations": result.operations,
            "uncalled": len(result.uncalled),
            "unknown_routes": len(result.unknown_route),
        },
    )
    return result
