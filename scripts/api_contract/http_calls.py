"""Which calls of the SDK's source send an HTTP request, and how.

A call sends by what its receiver is: the SDK's HTTP client (`self._http`,
`http`, ... with `request`, `stream_bytes`, `stream_sse_lines`), or an
`httpx` client opened with `with httpx.AsyncClient(...) as client` (with
`request`, `stream`, `post`, ...). A call of an SDK function or `self`
method sends what the client calls in it send with one of its parameters
as the path, such as auth's `_cp_post_async`. Any other call, a log
record or `cache.delete(...)`, sends nothing.

The method is the one the client method sends (`stream_bytes` reads,
`post` posts), or its method argument for `request` and `stream`; a helper
sends its inner call's method, or what its caller passes as that method.
A method argument that is not a literal is `?`, which no reference has, so
the check reports it as a route in neither reference.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from api_contract.reaching import position
from api_contract.reference import HTTP_METHODS
from api_contract.source import FunctionNode, Scope

__all__ = ["UNKNOWN_METHOD", "Request", "requests"]

#: How a client method sends: the method it sends, or the position of its
#: method argument, and the position of its path argument.
Signature = tuple[str | int, int]

#: The SDK's HTTP client, by method, and the keyword of its path.
SDK_CLIENT: dict[str, Signature] = {
    "request": (0, 1),
    "stream_bytes": ("GET", 0),
    "stream_sse_lines": ("GET", 0),
}
SDK_PATH = "path"
#: An `httpx` client, by method, and the keyword of its path.
HTTPX_CLIENT: dict[str, Signature] = {
    "request": (0, 1),
    "stream": (0, 1),
    **{method: (method.upper(), 0) for method in HTTP_METHODS},
}
HTTPX_PATH = "url"
HTTPX_CLIENTS = ("AsyncClient", "Client")
MAX_DEPTH = 8
UNKNOWN_METHOD = "?"


@dataclass(frozen=True)
class Request:
    """An HTTP request a call sends: its method, or the expression that
    gives it, and the expression of its path, both as the call reads
    them."""

    method: str | ast.expr | None
    path: ast.expr | None

    @property
    def method_name(self) -> str:
        method = self.method
        if isinstance(method, str):
            return method
        if (
            isinstance(method, ast.Constant)
            and isinstance(method.value, str)
            and method.value.lower() in HTTP_METHODS
        ):
            return method.value.upper()
        return UNKNOWN_METHOD


def requests(call: ast.Call, scope: Scope, depth: int = 0) -> list[Request]:
    """The HTTP requests `call` sends: one for a client call, and for a
    call of an SDK function or method, each client call it passes one of
    its parameters to as the path."""
    func = call.func
    if isinstance(func, ast.Attribute):
        client = _client(func, scope)
        if client is not None:
            methods, keyword = client
            method, at = methods[func.attr]
            return [
                Request(
                    method
                    if isinstance(method, str)
                    else _argument(call, method, "method"),
                    _argument(call, at, keyword),
                )
            ]
    found = scope.callee(func) if depth < MAX_DEPTH else None
    if found is None:
        return []
    return _forwarded(call, *found, depth)


def _client(
    func: ast.Attribute, scope: Scope
) -> tuple[dict[str, Signature], str] | None:
    """The client methods of the receiver of `func`, and the keyword of
    their path, when it is an HTTP client that has `func.attr`."""
    receiver = func.value
    name = (
        receiver.attr
        if isinstance(receiver, ast.Attribute)
        else receiver.id
        if isinstance(receiver, ast.Name)
        else ""
    )
    if func.attr in SDK_CLIENT and (name == "http" or name.endswith("_http")):
        return SDK_CLIENT, SDK_PATH
    if func.attr in HTTPX_CLIENT and isinstance(receiver, ast.Name):
        if _opens_httpx(receiver.id, scope):
            return HTTPX_CLIENT, HTTPX_PATH
    return None


def _opens_httpx(name: str, scope: Scope) -> bool:
    """Whether an enclosing function binds `name` with
    `with httpx.AsyncClient(...) as name` (or `httpx.Client`)."""
    return any(
        isinstance(item.optional_vars, ast.Name)
        and item.optional_vars.id == name
        and isinstance(item.context_expr, ast.Call)
        and isinstance(opened := item.context_expr.func, ast.Attribute)
        and isinstance(opened.value, ast.Name)
        and opened.value.id == "httpx"
        and opened.attr in HTTPX_CLIENTS
        for function in scope.chain
        for node in ast.walk(function)
        if isinstance(node, ast.With | ast.AsyncWith)
        for item in node.items
    )


def _argument(call: ast.Call, index: int, keyword: str) -> ast.expr | None:
    """The argument `call` passes at position `index`, or as `keyword`."""
    positional = call.args[: index + 1]
    if len(positional) > index and not any(
        isinstance(arg, ast.Starred) for arg in positional
    ):
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg == keyword), None)


def _forwarded(
    call: ast.Call,
    function: FunctionNode,
    inner: Scope,
    unpassed: int,
    depth: int,
) -> list[Request]:
    """The requests of the client calls `function` passes one of its
    parameters to as the path, with what `call` passes for it."""
    bound = _bind(function, call, unpassed)
    out: list[Request] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        for request in requests(node, inner, depth + 1):
            paths = _parameters(request.path, inner)
            method = request.method
            methods = (
                [bound.get(name) for name in _parameters(method, inner)]
                if isinstance(method, ast.expr)
                else []
            )
            for path in paths:
                if path in bound:
                    out.extend(
                        Request(value, bound[path])
                        for value in methods or [method]
                    )
    return out


def _bind(
    function: FunctionNode, call: ast.Call, unpassed: int
) -> dict[str, ast.expr]:
    """The expression `call` passes for each parameter of `function`."""
    spec = function.args
    positional = [*spec.posonlyargs, *spec.args]
    names = [p.arg for p in positional][unpassed:]
    out = {
        param.arg: default
        for param, default in zip(
            positional[len(positional) - len(spec.defaults) :],
            spec.defaults,
            strict=True,
        )
    }
    out.update(
        {
            param.arg: default
            for param, default in zip(
                spec.kwonlyargs, spec.kw_defaults, strict=True
            )
            if default is not None
        }
    )
    for name, arg in zip(names, call.args, strict=False):
        if isinstance(arg, ast.Starred):
            break
        out[name] = arg
    out.update({k.arg: k.value for k in call.keywords if k.arg is not None})
    return out


def _parameters(
    expr: ast.expr | None, scope: Scope, depth: int = 0
) -> list[str]:
    """Follow local aliases to every parameter that can supply a value."""
    if not isinstance(expr, ast.Name) or depth >= MAX_DEPTH:
        return []
    assigned = scope.assignments(
        expr.id,
        position(expr),
        incoming=expr if scope.is_parameter(expr.id) else None,
    )
    # The same expression stands for the incoming parameter. Do not walk
    # it again: only branches that preserve it should bind the caller's value.
    return list(
        dict.fromkeys(
            name
            for value in assigned
            for name in (
                [expr.id]
                if value is expr
                else _parameters(value, scope, depth + 1)
            )
        )
    )
