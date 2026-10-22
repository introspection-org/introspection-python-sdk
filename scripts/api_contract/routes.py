"""Every route this SDK sends, read from its source.

A route is sent where a `/v1/...` path is an argument of a call: the
SDK's HTTP client (`request`, `stream_bytes`, `stream_sse_lines`), a
helper such as auth's `_cp_post_async`, or `httpx` itself. The path may be
a literal, an f-string, a module constant, a local, or a call to a helper
that returns one (`_path(kind, name)`), in this module or imported from
another SDK module. Every `{...}` that is not a known route is read as a
path parameter. A route in any other position, a docstring or a comment,
is not a call.

The method is the call's literal `"GET"` / `"POST"` / ... argument, else
the one its callee's name says (`_cp_post_async` posts, `stream_bytes`
reads); a route sent without either cannot be classified and is reported.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from api_contract.reference import HTTP_METHODS
from api_contract.source import Package, Scope, SourceModule

__all__ = ["CallSite", "Discovery", "discover", "routes_of"]

#: Callee names, as substrings, that say which method a call sends.
CALLEE_METHODS = (
    ("post", "POST"),
    ("patch", "PATCH"),
    ("put", "PUT"),
    ("delete", "DELETE"),
    ("stream", "GET"),
    ("get", "GET"),
)
MAX_DEPTH = 8


@dataclass(frozen=True)
class CallSite:
    method: str
    path: str
    call: ast.Call
    scope: Scope

    @property
    def at(self) -> str:
        return self.scope.module.line(self.call)


@dataclass
class Discovery:
    sites: list[CallSite]
    unknown_method: list[str]


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
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        return _helper(expr.func.id, scope, depth)
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
    local = scope.assignment(expr.id, getattr(expr, "lineno", 0))
    if local is not None:
        return routes_of(local, scope, depth + 1)
    if scope.parameter(expr.id) is not None:
        return []
    found = scope.package.resolve_import(scope.module, expr.id)
    if found is None:
        return []
    module, name = found
    value = module.constants.get(name)
    return routes_of(value, Scope(scope.package, module, ()), depth + 1)


def _helper(name: str, scope: Scope, depth: int) -> list[str]:
    found = scope.package.resolve_import(scope.module, name)
    if found is None or found[1] not in found[0].functions:
        return []
    module, fname = found
    function = module.functions[fname]
    inner = scope.inside(module, function)
    out: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return):
            out += routes_of(node.value, inner, depth + 1)
    return out


def _method(call: ast.Call) -> str | None:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value.lower() in HTTP_METHODS:
                return arg.value.upper()
    for kw in call.keywords:
        if kw.arg == "method" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value).upper()
    func = call.func
    callee = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id
        if isinstance(func, ast.Name)
        else ""
    ).lower()
    return next((m for word, m in CALLEE_METHODS if word in callee), None)


def _module_sites(package: Package, module: SourceModule) -> Discovery:
    found = Discovery(sites=[], unknown_method=[])
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        scope = Scope.of(package, module, node)
        args = [
            *node.args,
            *(k.value for k in node.keywords if k.arg in ("path", "url")),
        ]
        paths = sorted(
            {
                p.split("?")[0]
                for arg in args
                for p in routes_of(arg, scope)
                if p.startswith("/v1/")
            }
        )
        if not paths:
            continue
        method = _method(node)
        for path in paths:
            if method is None:
                found.unknown_method.append(f"{path} ({module.line(node)})")
            else:
                found.sites.append(CallSite(method, path, node, scope))
    return found


def discover(package: Package) -> Discovery:
    found = Discovery(sites=[], unknown_method=[])
    for module in package.modules.values():
        own = _module_sites(package, module)
        found.sites += own.sites
        found.unknown_method += own.unknown_method
    return found
