"""The JSON Schema of what a Python expression in the SDK evaluates to.

Python keeps its types at runtime, so the SDK side is pydantic's own JSON
Schema of the type that goes on the wire: the model a body is dumped from,
the model or `TypeAdapter` a response is validated with, a parameter's
annotation. The expression is read from the source (see routes) and each
name in it is resolved in the module the SDK itself imports, so an
inherited field or a nested model is in the schema because it is in the
class.

What cannot be read this way (an untyped `dict`, `Any`, a value built by
code this reader does not follow) raises `Unresolved` with the reason,
which the check prints as a warning rather than passing it as checked.
"""

from __future__ import annotations

import ast
import builtins
from typing import Any

from pydantic import BaseModel

from api_contract.json_schema import (
    Unresolved,
    array,
    is_nullable,
    obj,
    type_schema,
    union,
    with_defs,
)
from api_contract.source import FunctionNode, Scope, SourceModule

__all__ = ["ExpressionReader", "Unresolved"]

MAX_DEPTH = 10
SCALARS = {
    str: {"type": "string"},
    bool: {"type": "boolean"},
    int: {"type": "integer"},
    float: {"type": "number"},
}
STRING_METHODS = {
    "isoformat",
    "hex",
    "lower",
    "upper",
    "strip",
    "format",
    "join",
    "decode",
    "model_dump_json",
}
VALIDATORS = {
    "model_validate",
    "model_validate_json",
    "validate_python",
    "validate_json",
    "model_construct",
}


def _is_reference(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return True
    if isinstance(expr, ast.Attribute):
        return _is_reference(expr.value)
    if isinstance(expr, ast.Subscript):
        return _is_reference(expr.value) and all(
            _is_reference(e) or isinstance(e, ast.Constant)
            for e in (
                expr.slice.elts
                if isinstance(expr.slice, ast.Tuple)
                else [expr.slice]
            )
        )
    return False


class ExpressionReader:
    """Reads expressions in one scope; `mode` is pydantic's JSON Schema
    mode: "serialization" for what the SDK sends, "validation" for what it
    reads."""

    def __init__(self, scope: Scope, mode: str, depth: int = 0) -> None:
        self.scope = scope
        self.mode = mode
        self.depth = depth

    def within(self, scope: Scope) -> ExpressionReader:
        if self.depth >= MAX_DEPTH:
            raise Unresolved("nested too deep")
        return ExpressionReader(scope, self.mode, self.depth + 1)

    # --- runtime values ----------------------------------------------------

    def runtime(self, expr: ast.expr) -> Any:
        """The value a name, attribute or subscript of names has in the
        module, as the SDK itself sees it."""
        module = self.scope.module.runtime
        if module is None or not _is_reference(expr):
            raise Unresolved(f"not a name ({ast.unparse(expr)})")
        try:
            return eval(ast.unparse(expr), dict(vars(module)))  # noqa: S307
        except Exception as exc:
            raise Unresolved(f"cannot resolve {ast.unparse(expr)}") from exc

    def annotation(self, ann: ast.expr | None, what: str) -> dict[str, Any]:
        if ann is None:
            raise Unresolved(f"unannotated {what}")
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            ann = ast.parse(ann.value, mode="eval").body
        module = self.scope.module.runtime
        namespace = {**vars(builtins), **(vars(module) if module else {})}
        try:
            tp = eval(ast.unparse(ann), namespace)  # noqa: S307
        except Exception as exc:
            raise Unresolved(f"cannot resolve {ast.unparse(ann)}") from exc
        if tp is Any:
            raise Unresolved(f"{what} is Any")
        return type_schema(tp, self.mode)

    def returns(self, function: FunctionNode) -> dict[str, Any]:
        return self.annotation(function.returns, f"return of {function.name}")

    # --- expressions -------------------------------------------------------

    def read(self, expr: ast.expr) -> dict[str, Any]:
        handler = getattr(self, f"_read_{type(expr).__name__}", None)
        if handler is None:
            raise Unresolved(f"{type(expr).__name__} expression")
        return handler(expr)

    def _read_Constant(self, expr: ast.Constant) -> dict[str, Any]:
        if expr.value is None:
            return {"type": "null"}
        for tp, schema in SCALARS.items():
            if type(expr.value) is tp:
                return dict(schema)
        raise Unresolved(f"constant {expr.value!r}")

    def _read_JoinedStr(self, expr: ast.JoinedStr) -> dict[str, Any]:
        return {"type": "string"}

    def _read_IfExp(self, expr: ast.IfExp) -> dict[str, Any]:
        return union([self.read(expr.body), self.read(expr.orelse)])

    def _read_BoolOp(self, expr: ast.BoolOp) -> dict[str, Any]:
        return union([self.read(v) for v in expr.values])

    def _read_Await(self, expr: ast.Await) -> dict[str, Any]:
        return self.read(expr.value)

    def _read_List(self, expr: ast.List | ast.Tuple) -> dict[str, Any]:
        items = [self._or_untyped(e) for e in expr.elts]
        return array(union(items) if items else {})

    _read_Tuple = _read_List

    def _read_ListComp(self, expr: ast.ListComp) -> dict[str, Any]:
        return array(self._or_untyped(expr.elt))

    _read_SetComp = _read_ListComp
    _read_GeneratorExp = _read_ListComp

    def _read_DictComp(self, expr: ast.DictComp) -> dict[str, Any]:
        """`{k: v for k, v in body.items() if ...}` filters `body`'s
        fields, so it has `body`'s schema."""
        loop = expr.generators[0]
        if (
            len(expr.generators) == 1
            and isinstance(loop.iter, ast.Call)
            and isinstance(loop.iter.func, ast.Attribute)
            and loop.iter.func.attr == "items"
            and isinstance(loop.target, ast.Tuple)
            and [ast.unparse(e) for e in loop.target.elts]
            == [ast.unparse(expr.key), ast.unparse(expr.value)]
        ):
            return self.read(loop.iter.func.value)
        return {"type": "object"}

    def _read_Attribute(self, expr: ast.Attribute) -> dict[str, Any]:
        if expr.attr == "value":  # an enum's value
            return self.read(expr.value)
        raise Unresolved(f"attribute {ast.unparse(expr)}")

    def _or_untyped(self, expr: ast.expr) -> dict[str, Any]:
        try:
            return self.read(expr)
        except Unresolved:
            return {}

    def _read_Dict(self, expr: ast.Dict) -> dict[str, Any]:
        props: dict[str, dict[str, Any]] = {}
        required: list[str] = []
        for key, value in zip(expr.keys, expr.values, strict=True):
            if key is None:  # `**spread`
                spread = self.read(value)
                props.update(spread.get("properties") or {})
                required += spread.get("required") or []
                continue
            if not isinstance(key, ast.Constant):
                raise Unresolved("a dict with computed keys")
            schema = self._or_untyped(value)
            props[str(key.value)] = schema
            if schema and not is_nullable(schema):
                required.append(str(key.value))
        return obj(props, required)

    def _read_Name(self, expr: ast.Name) -> dict[str, Any]:
        line = getattr(expr, "lineno", 0)
        local = self.scope.assignment(expr.id, line)
        if local is not None:
            schema = self.read(local)
            return self._with_item_writes(expr.id, schema)
        found = self.scope.parameter(expr.id)
        if found is not None:
            function, arg = found
            return self.within(
                Scope(self.scope.package, self.scope.module, (function,))
            ).annotation(arg.annotation, f"parameter {arg.arg}")
        constant = self.scope.module.constants.get(expr.id)
        if constant is not None:
            module_scope = Scope(self.scope.package, self.scope.module, ())
            return self.within(module_scope).read(constant)
        raise Unresolved(f"name {expr.id}")

    def _with_item_writes(
        self, name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """`params["key"] = value` after `params = {...}` adds an optional
        field."""
        if "properties" not in schema or not self.scope.chain:
            return schema
        props = dict(schema["properties"])
        defs = dict(schema.get("$defs") or {})
        props = {k: with_defs(v, defs) for k, v in props.items()}
        for node in ast.walk(self.scope.chain[0]):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == name
                    and isinstance(target.slice, ast.Constant)
                ):
                    props.setdefault(
                        str(target.slice.value), self._or_untyped(node.value)
                    )
        return obj(props, list(schema.get("required") or ()))

    def _read_Call(self, expr: ast.Call) -> dict[str, Any]:
        func = expr.func
        if isinstance(func, ast.Name) and func.id in vars(builtins):
            return self._builtin(func.id, expr)
        if isinstance(func, ast.Attribute):
            if func.attr == "model_dump":
                return self.read(func.value)
            if func.attr in STRING_METHODS:
                return {"type": "string"}
            if func.attr in VALIDATORS:
                return type_schema(self.runtime(func.value), self.mode)
        if isinstance(func, ast.Name):
            helper = self.scope.package.resolve_import(
                self.scope.module, func.id
            )
            if helper is not None and helper[1] in helper[0].functions:
                module, name = helper
                return self._helper(module, name)
        return self._called(func)

    def _builtin(self, name: str, expr: ast.Call) -> dict[str, Any]:
        tp = getattr(builtins, name)
        if tp in SCALARS:
            return dict(SCALARS[tp])
        if name in ("list", "tuple", "sorted", "set") and expr.args:
            inner = self._or_untyped(expr.args[0])
            return inner if inner.get("type") == "array" else array({})
        if name == "dict":
            return self.read(expr.args[0]) if expr.args else {"type": "object"}
        if name == "len":
            return {"type": "integer"}
        raise Unresolved(f"{name}(...)")

    def _helper(self, module: SourceModule, name: str) -> dict[str, Any]:
        """A function in the SDK: the union of what its returns read as,
        else its return annotation."""
        function = module.functions[name]
        inner = self.within(Scope(self.scope.package, module, (function,)))
        values = [
            n.value
            for n in ast.walk(function)
            if isinstance(n, ast.Return) and n.value is not None
        ]
        try:
            if not values:
                raise Unresolved(f"{name} returns nothing")
            return union([inner.read(v) for v in values])
        except Unresolved:
            return inner.returns(function)

    def _called(self, func: ast.expr) -> dict[str, Any]:
        value = self.runtime(func)
        if isinstance(value, type) and issubclass(value, BaseModel):
            return type_schema(value, self.mode)
        hints = getattr(value, "__annotations__", {})
        if "return" in hints and not isinstance(hints["return"], str):
            if hints["return"] is Any:
                raise Unresolved(f"{ast.unparse(func)} returns Any")
            return type_schema(hints["return"], self.mode)
        raise Unresolved(f"call to {ast.unparse(func)}")
