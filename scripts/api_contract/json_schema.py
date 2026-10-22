"""Building JSON Schema for the SDK side, the way pydantic writes it: every
named model under one `$defs` at the root, so a `$ref` resolves wherever
the schema it sits in was combined into."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

__all__ = [
    "Unresolved",
    "array",
    "is_nullable",
    "obj",
    "type_schema",
    "union",
    "with_defs",
]


class Unresolved(Exception):
    """An expression whose type says nothing about the wire."""


def _lift(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    inner = dict(schema)
    defs.update(inner.pop("$defs", {}))
    return inner


def with_defs(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    return {**schema, "$defs": defs} if defs else schema


def union(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    if len(schemas) == 1:
        return schemas[0]
    defs: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    for schema in schemas:
        inner = _lift(schema, defs)
        for part in inner["anyOf"] if set(inner) == {"anyOf"} else [inner]:
            if part not in parts:
                parts.append(part)
    if len(parts) == 1:
        return with_defs(parts[0], defs)
    return with_defs({"anyOf": parts}, defs)


def obj(
    props: dict[str, dict[str, Any]], required: list[str]
) -> dict[str, Any]:
    defs: dict[str, Any] = {}
    properties = {k: _lift(v, defs) for k, v in props.items()}
    schema = {"type": "object", "properties": properties, "required": required}
    return with_defs(schema, defs)


def array(items: dict[str, Any]) -> dict[str, Any]:
    defs: dict[str, Any] = {}
    return with_defs({"type": "array", "items": _lift(items, defs)}, defs)


def is_nullable(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    return any(is_nullable(s) for s in schema.get("anyOf") or ())


def type_schema(tp: Any, mode: str) -> dict[str, Any]:
    """pydantic's JSON Schema for a type or a `TypeAdapter`."""
    try:
        adapter = tp if isinstance(tp, TypeAdapter) else TypeAdapter(tp)
        return adapter.json_schema(mode=mode)  # type: ignore[arg-type]
    except Exception as exc:
        raise Unresolved(f"no JSON Schema for {tp!r}") from exc
