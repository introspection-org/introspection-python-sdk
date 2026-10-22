"""The contract check: this SDK against both API references.

It fails when

1. an operation whose `x-introspection.clients` includes `sdk` has no call
   site in the SDK;
2. the SDK calls a `/v1/...` route that is in neither reference (or sends
   one without a method it can be classified by);
3. a call site's request body, query parameters or response disagree with
   its operation's schemas: a field missing or extra, required in the
   reference but optional in the SDK, or of another basic type, following
   `$ref` into nested schemas.

A call site whose types cannot be read (an untyped `dict`, `Any`) is a
warning naming the operation, the part and the call site. It never fails
the run: fixing it is SDK work on the call site's types, not drift in the
API.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from api_contract.call_types import site_types
from api_contract.fields import Finding
from api_contract.reference import CLIENT, Operation, operations, shapes
from api_contract.routes import CallSite, discover
from api_contract.site_check import compare_site
from api_contract.source import Package

__all__ = ["FINDING_MEANS", "FieldProblem", "Result", "TypeWarning", "run"]

FINDING_MEANS = {
    "missing": "field missing in SDK (in the reference, but this call site "
    "neither sends nor reads it)",
    "extra": "field extra in SDK (this call site sends or reads it, but the "
    "reference does not have it)",
    "required": "required mismatch",
    "type": "type mismatch",
}


@dataclass(frozen=True)
class FieldProblem:
    operation: str
    at: str
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class TypeWarning:
    operation: str
    field: str
    detail: str
    at: str


@dataclass
class Result:
    operations: int = 0
    uncalled: list[str] = field(default_factory=list)
    unknown_route: list[str] = field(default_factory=list)
    unknown_method: list[str] = field(default_factory=list)
    fields: list[FieldProblem] = field(default_factory=list)
    warnings: list[TypeWarning] = field(default_factory=list)
    checked: int = 0

    @property
    def failed(self) -> bool:
        return bool(
            self.uncalled
            or self.unknown_route
            or self.unknown_method
            or self.fields
        )

    def counts(self) -> dict[str, int]:
        kinds: dict[str, int] = defaultdict(int)
        for problem in self.fields:
            for finding in problem.findings:
                kinds[finding.kind] += 1
        return {
            "sdk operation never called": len(self.uncalled),
            "route in neither reference": len(self.unknown_route),
            "route without a method": len(self.unknown_method),
            "call sites with field findings": len(self.fields),
            **{f"field {kind}": n for kind, n in sorted(kinds.items())},
            "warnings (no concrete types)": len(self.warnings),
        }


def _check_site(
    result: Result, spec: dict[str, Any], op: Operation, site: CallSite
) -> None:
    findings = compare_site(spec, shapes(spec, op), site_types(site))
    fatal = []
    for f in findings:
        if f.kind == "unresolvable":
            result.warnings.append(
                TypeWarning(op.name, f.field, f.detail, site.at)
            )
        else:
            fatal.append(f)
    if fatal:
        result.fields.append(FieldProblem(op.name, site.at, tuple(fatal)))


def run(package: Package, specs: dict[str, dict[str, Any]]) -> Result:
    """`specs` maps a plane name (`controlplane`, `dataplane`) to its
    document."""
    result = Result()
    by_key: dict[str, list[Operation]] = defaultdict(list)
    for plane, spec in specs.items():
        for op in operations(plane, spec):
            by_key[op.key].append(op)
            result.operations += 1
    discovery = discover(package)
    result.unknown_method = sorted(set(discovery.unknown_method))
    called: dict[Operation, list[CallSite]] = defaultdict(list)
    for site in discovery.sites:
        ops = by_key.get(f"{site.method} {site.path}")
        if not ops:
            result.unknown_route.append(
                f"{site.method} {site.path} ({site.at})"
            )
            continue
        for op in ops:
            called[op].append(site)
    for ops in by_key.values():
        for op in ops:
            if CLIENT in op.clients and op not in called:
                result.uncalled.append(op.name)
    for op in sorted(called, key=lambda o: o.name):
        result.checked += 1
        for site in called[op]:
            _check_site(result, specs[op.plane], op, site)
    result.uncalled.sort()
    result.unknown_route.sort()
    return result
