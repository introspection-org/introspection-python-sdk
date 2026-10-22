"""Every route this SDK sends, read from its source.

A route is sent where a `/v1/...` path is an argument of an HTTP call:
the SDK's HTTP client (`request`, `stream_bytes`, `stream_sse_lines`),
`httpx` itself (`post`, ...), or an SDK function that passes one of its
parameters to such a call, such as auth's `_cp_post_async`. The path may be
a literal, an f-string, a module constant, a local, or a call to a helper
that returns one (`_path(kind, name)`), in this module or imported from
another SDK module. Every `{...}` that is not a known route is read as a
path parameter. A route in any other position, a docstring or a comment,
is not a call, and neither is a path in any other call (a log record,
say).

The method is the one the client method sends (`stream_bytes` reads,
`post` posts), or the call's literal `"GET"` / `"POST"` / ... argument for
`request`; a helper sends its inner call's method. A `request` whose
method is not a literal has method `?`, which no reference has, so the
check reports it as a route in neither reference.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass

from api_contract.reference import HTTP_METHODS
from api_contract.source import Package, Scope, SourceModule

__all__ = ["UNKNOWN_METHOD", "CallSite", "discover", "routes_of"]

#: The client methods a route is sent with, by name, and the method each
#: sends; `None` reads it from the call's arguments.
CLIENT_METHODS: dict[str, str | None] = {
    "request": None,
    "stream_bytes": "GET",
    "stream_sse_lines": "GET",
    **{method: method.upper() for method in HTTP_METHODS},
}
MAX_DEPTH = 8
UNKNOWN_METHOD = "?"

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
    local = scope.assignments(expr.id, getattr(expr, "lineno", 0))
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


def _path_args(call: ast.Call) -> list[ast.expr]:
    return [
        *call.args,
        *(k.value for k in call.keywords if k.arg in ("path", "url")),
    ]


def _literal_method(call: ast.Call) -> str:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value.lower() in HTTP_METHODS:
                return arg.value.upper()
    for kw in call.keywords:
        if kw.arg == "method" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value).upper()
    return UNKNOWN_METHOD


def _method(call: ast.Call, scope: Scope, depth: int = 0) -> str | None:
    """The method `call` sends, or `None` when it is no HTTP call."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in CLIENT_METHODS:
        return CLIENT_METHODS[func.attr] or _literal_method(call)
    if isinstance(func, ast.Name) and depth < MAX_DEPTH:
        return _forwarded(func.id, scope, depth)
    return None


def _forwarded(name: str, scope: Scope, depth: int) -> str | None:
    """The method of the HTTP call SDK function `name` passes one of its
    parameters to, if it has one."""
    found = scope.package.resolve_import(scope.module, name)
    if found is None or found[1] not in found[0].functions:
        return None
    module, fname = found
    function = module.functions[fname]
    inner = scope.inside(module, function)
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and any(
            isinstance(arg, ast.Name) and inner.is_parameter(arg.id)
            for arg in _path_args(node)
        ):
            method = _method(node, inner, depth + 1)
            if method is not None:
                return method
    return None


def _module_sites(package: Package, module: SourceModule) -> list[CallSite]:
    found: list[CallSite] = []
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        scope = Scope.of(package, module, node)
        paths = sorted(
            {
                p.split("?")[0]
                for arg in _path_args(node)
                for p in routes_of(arg, scope)
                if p.startswith("/v1/")
            }
        )
        method = _method(node, scope) if paths else None
        if method is None:
            continue
        found += [CallSite(method, path, module.line(node)) for path in paths]
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
