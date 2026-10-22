"""Every route this SDK sends, read from its source.

A route is sent where a `/v1/...` path is the path of a request a call
sends (see `api_contract.http_calls`). The path may be a literal, an
f-string, a module constant, a local, or a call to a helper that returns
one (`_path(kind, name)`), in this module or imported from another SDK
module. Every `{...}` that is not a known route is read as a path
parameter. A route in any other position, a docstring or a comment, is
not a call, and neither is a path in a call that sends no request (a log
record, `cache.delete(...)`).
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass

from api_contract.http_calls import requests
from api_contract.source import Package, Scope, SourceModule

__all__ = [
    "CallSite",
    "discover",
    "route_arguments",
    "routes_of",
]

MAX_DEPTH = 8

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallSite:
    method: str
    path: str
    at: str


def routes_of(
    expr: ast.expr | None, scope: Scope, depth: int = 0
) -> list[str]:
    """The path templates an expression can evaluate to, unfiltered: a
    suffix such as `"/stream"` is returned too, so `path + "/stream"`
    resolves."""
    if expr is None or depth > MAX_DEPTH:
        return []
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.JoinedStr):
        return _joined(expr, scope, depth)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        rights = routes_of(expr.right, scope, depth + 1)
        return [
            left + right
            for left in routes_of(expr.left, scope, depth + 1)
            for right in rights
        ]
    if isinstance(expr, ast.IfExp):
        return routes_of(expr.body, scope, depth + 1) + routes_of(
            expr.orelse, scope, depth + 1
        )
    if isinstance(expr, ast.Name):
        return _name(expr, scope, depth)
    if isinstance(expr, ast.Call):
        return _helper(expr.func, scope, depth)
    return []


def _joined(expr: ast.JoinedStr, scope: Scope, depth: int) -> list[str]:
    prefixes = [""]
    for i, part in enumerate(expr.values):
        if isinstance(part, ast.Constant):
            prefixes = [p + str(part.value) for p in prefixes]
            continue
        assert isinstance(part, ast.FormattedValue)
        base = [
            r
            for r in (
                routes_of(part.value, scope, depth + 1) if i == 0 else []
            )
            if r.startswith("/")
        ]
        prefixes = base or [p + "{}" for p in prefixes]
    # A leading `{...}` before `/v1/` is the base URL, not a parameter.
    return [p[2:] if p.startswith("{}/v1/") else p for p in prefixes]


def _name(expr: ast.Name, scope: Scope, depth: int) -> list[str]:
    local = scope.assignments(expr.id, (expr.lineno, expr.col_offset))
    if local:
        return [
            r for value in local for r in routes_of(value, scope, depth + 1)
        ]
    if scope.is_parameter(expr.id):
        return []
    found = scope.package.resolve_import(scope.module, expr.id)
    if found is None:
        return []
    module, name = found
    value = module.constants.get(name)
    return routes_of(value, Scope(scope.package, module, ()), depth + 1)


def _helper(func: ast.expr, scope: Scope, depth: int) -> list[str]:
    found = scope.callee(func)
    if found is None:
        return []
    function, inner, _ = found
    out: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return):
            out += routes_of(node.value, inner, depth + 1)
    return out


def route_arguments(call: ast.Call, scope: Scope) -> list[str]:
    """The `/v1/` routes any argument of `call` that may be a path can
    evaluate to, whether or not `call` sends them."""
    return sorted(
        {
            p.split("?")[0]
            for arg in [
                *call.args,
                *(k.value for k in call.keywords if k.arg in ("path", "url")),
            ]
            for p in routes_of(arg, scope)
            if p.startswith("/v1/")
        }
    )


def _module_sites(package: Package, module: SourceModule) -> list[CallSite]:
    found: list[CallSite] = []
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        scope = Scope.of(package, module, node)
        # Only a call that passes a route can send one; this skips the
        # helper lookups of every other call.
        if not route_arguments(node, scope):
            continue
        sites = {
            CallSite(request.method_name, p.split("?")[0], module.line(node))
            for request in requests(node, scope)
            for p in routes_of(request.path, scope)
            if p.startswith("/v1/")
        }
        found += sorted(sites, key=lambda s: (s.method, s.path))
    return found


def discover(package: Package) -> list[CallSite]:
    found = [
        site
        for module in package.modules.values()
        for site in _module_sites(package, module)
    ]
    logger.debug(
        "call sites discovered",
        extra={"sites": len(found), "modules": len(package.modules)},
    )
    return found
