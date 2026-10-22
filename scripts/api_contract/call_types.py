"""The request body, query parameters and response at one call site.

The body is the call's `json=` (or a form: `files=` is multipart,
`data=` is urlencoded), the query its `params=`. The response is whatever
the call's result is validated with: `Model.model_validate(payload)`,
`ADAPTER.validate_python(...)`, a helper that does either, or the
enclosing function's return annotation when the result is returned as is.
A call that reads no JSON (`expect="empty" | "bytes" | "raw"`, a stream)
or discards its result has no response fields to compare.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from api_contract.expressions import ExpressionReader, Unresolved
from api_contract.fields import kind_of
from api_contract.routes import CallSite
from api_contract.source import FunctionNode, Scope

__all__ = ["Slot", "SiteTypes", "site_types"]

FORM_MEDIA = {
    "files": "multipart/form-data",
    "data": "application/x-www-form-urlencoded",
}


@dataclass(frozen=True)
class Slot:
    """One part of a call site: a JSON Schema, or why there is none to
    compare (`unresolved`), or the non-JSON media it carries."""

    schema: dict[str, Any] | None = None
    unresolved: str = ""
    media: str = "application/json"
    not_json: str = ""


@dataclass(frozen=True)
class SiteTypes:
    body: Slot | None
    query: Slot | None
    response: Slot | None
    accept: str | None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def top_level(schema: dict[str, Any]) -> str:
    """Why a top-level body, query or response compares nothing, or ""."""
    branches = [
        s
        for s in schema.get("anyOf") or schema.get("oneOf") or [schema]
        if s.get("type") != "null"
    ]
    if not branches or any("$ref" in s or "allOf" in s for s in branches):
        return ""
    if all(kind_of(s) == "any" and "$ref" not in s for s in branches):
        return "untyped"
    if all(kind_of(s) == "string" for s in branches):
        return "serialized before the call (string)"
    if all(
        kind_of(s) == "object" and not s.get("properties") and "$ref" not in s
        for s in branches
    ):
        return "no named fields (dict)"
    return ""


def _slot(reader: ExpressionReader, expr: ast.expr) -> Slot:
    try:
        schema = reader.read(expr)
    except Unresolved as exc:
        return Slot(unresolved=str(exc))
    why = top_level(schema)
    return Slot(unresolved=why) if why else Slot(schema=schema)


def _body(site: CallSite) -> Slot | None:
    reader = ExpressionReader(site.scope, "serialization")
    payload = _keyword(site.call, "json")
    if payload is not None:
        return _slot(reader, payload)
    for name, media in FORM_MEDIA.items():
        if _keyword(site.call, name) is not None:
            return Slot(media=media, not_json="form")
    return None


def _query(site: CallSite) -> Slot | None:
    params = _keyword(site.call, "params")
    if params is None:
        return None
    return _slot(ExpressionReader(site.scope, "serialization"), params)


#: An Accept header the call site does not spell out as one literal.
NOT_LITERAL = "not a literal"


def _header_values(expr: ast.expr, scope: Scope) -> list[Any]:
    """The header dicts an expression can be: a literal, a constant, or a
    helper in this module that returns one of several."""
    if isinstance(expr, ast.Dict):
        return [
            {
                k.value: v.value
                for k, v in zip(expr.keys, expr.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
        ]
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        function = scope.module.functions.get(expr.func.id)
        if function is None:
            return []
        inner = scope.inside(scope.module, function)
        return [
            value
            for node in ast.walk(function)
            if isinstance(node, ast.Return) and node.value is not None
            for value in _header_values(node.value, inner)
        ]
    try:
        return [ExpressionReader(scope, "validation").runtime(expr)]
    except Unresolved:
        return []


def _accept(site: CallSite) -> str | None:
    """The media type the call asks for: None without an Accept header
    (the client then reads JSON), else the header, else NOT_LITERAL."""
    headers = _keyword(site.call, "headers")
    if headers is None:
        return None
    accepts = {
        next(
            (str(v) for k, v in value.items() if str(k).lower() == "accept"),
            None,
        )
        for value in _header_values(headers, site.scope)
        if isinstance(value, dict)
    }
    if not accepts:
        return NOT_LITERAL
    if len(accepts) > 1:
        return NOT_LITERAL
    return accepts.pop()


def _consumer(site: CallSite) -> ast.expr | FunctionNode | None:
    """The expression that reads the call's result, or the function whose
    return annotation types it."""
    parents = site.scope.module.parents
    node: ast.AST = site.call
    parent = parents.get(node)
    while isinstance(parent, ast.Await):
        node, parent = parent, parents.get(parent)
    if isinstance(parent, ast.Call) and node in parent.args:
        return parent
    if isinstance(parent, ast.Return):
        return site.scope.chain[0] if site.scope.chain else None
    if (
        isinstance(parent, ast.Assign)
        and len(parent.targets) == 1
        and isinstance(parent.targets[0], ast.Name)
    ):
        return _reader_of(site, parent.targets[0].id, parent.lineno)
    return None


def _reader_of(
    site: CallSite, name: str, line: int
) -> ast.expr | FunctionNode | None:
    """The first call after `line` that takes `name` (or `name.json()`),
    or the function when `name` is returned as is."""
    if not site.scope.chain:
        return None
    function = site.scope.chain[0]
    for node in sorted(
        (n for n in ast.walk(function) if getattr(n, "lineno", 0) > line),
        key=lambda n: (n.lineno, n.col_offset),
    ):
        if isinstance(node, ast.Call) and any(
            _is_result(a, name) for a in node.args
        ):
            return node
        if isinstance(node, ast.Return) and _is_result(node.value, name):
            return function
    return None


def _is_result(expr: ast.expr | None, name: str) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == name
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "json"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == name
    )


def _response(site: CallSite) -> Slot | None:
    func = site.call.func
    callee = func.attr if isinstance(func, ast.Attribute) else ""
    if callee.startswith("stream"):
        return Slot(not_json="stream")
    expect = _keyword(site.call, "expect")
    if isinstance(expect, ast.Constant) and expect.value != "json":
        return Slot(not_json=f"{expect.value} body")
    consumer = _consumer(site)
    reader = ExpressionReader(site.scope, "validation")
    if consumer is None:
        return None
    if isinstance(consumer, ast.expr):
        return _slot(reader, consumer)
    try:
        schema = reader.returns(consumer)
    except Unresolved as exc:
        return Slot(unresolved=str(exc))
    why = top_level(schema)
    return Slot(unresolved=why) if why else Slot(schema=schema)


def site_types(site: CallSite) -> SiteTypes:
    return SiteTypes(
        body=_body(site),
        query=_query(site),
        response=_response(site),
        accept=_accept(site),
    )
