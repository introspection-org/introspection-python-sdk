"""The check's result as text: problems first, then the warnings."""

from __future__ import annotations

from collections import defaultdict

from api_contract.check import FINDING_MEANS, FieldProblem, Result

__all__ = ["render"]


def _listing(items: list[str], indent: str = "      ") -> str:
    return "".join(f"\n{indent}{item}" for item in items)


def _field_problems(problems: list[FieldProblem]) -> list[str]:
    by_operation: dict[str, list[FieldProblem]] = defaultdict(list)
    for problem in problems:
        by_operation[problem.operation].append(problem)
    out = []
    for operation, sites in sorted(by_operation.items()):
        lines = [f"fields — {operation}"]
        for site in sites:
            lines.append(f"  {site.at}")
            groups: dict[str, list[str]] = defaultdict(list)
            for f in site.findings:
                groups[f.kind].append(
                    f"{f.field} ({f.detail})" if f.detail else f.field
                )
            for kind, fields in groups.items():
                lines.append(
                    f"    {FINDING_MEANS[kind]}:"
                    + _listing(sorted(fields), "        ")
                )
        out.append("\n".join(lines))
    return out


def _warnings(result: Result) -> str:
    by_operation: dict[str, list[str]] = defaultdict(list)
    for w in result.warnings:
        by_operation[w.operation].append(
            f"{w.field}{f': {w.detail}' if w.detail else ''} ({w.at})"
        )
    lines = [
        "Warning: SDK has no concrete types (does not fail; give these call "
        "sites concrete types so their fields are checked)"
    ]
    for operation, items in sorted(by_operation.items()):
        lines.append(f"  {operation}" + _listing(items, "    "))
    return "\n".join(lines)


def render(result: Result) -> str:
    sections = []
    operations = [
        (
            result.uncalled,
            "operations — flagged for the SDK in x-introspection but no call "
            "site in introspection_sdk/ sends it",
        ),
        (
            result.unknown_route,
            "operations — called by this SDK but in neither API reference "
            "(the SDK calls a route that does not exist)",
        ),
        (
            result.unknown_method,
            "operations — a route sent without a literal method, so it cannot "
            "be classified",
        ),
    ]
    for items, means in operations:
        if items:
            sections.append(f"{means}:{_listing(items)}")
    sections += _field_problems(result.fields)
    if result.warnings:
        sections.append(_warnings(result))
    counts = ", ".join(f"{n} {what}" for what, n in result.counts().items())
    verdict = (
        f"✗ SDK surface disagrees with the API references ({counts})"
        if result.failed
        else f"✓ SDK surface matches the API references ({result.operations} "
        f"operations, {result.checked} field-checked, "
        f"{len(result.warnings)} call-site warnings)"
    )
    sections.append(verdict)
    return "\n\n".join(sections)
