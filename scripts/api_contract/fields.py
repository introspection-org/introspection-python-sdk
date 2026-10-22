"""Field-by-field comparison of a reference schema with an SDK schema.

Both sides are JSON Schema: the reference's from its OpenAPI document, the
SDK's from pydantic (see sdk_types). Comparing one representation with
itself means `$ref`, `anyOf`, `required` and discriminated unions are read
the same way on both sides.

Nullability is not compared: the reference writes an optional field as
`anyOf: [T, null]` throughout, so it would flag nearly every field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api_contract.reference import deref

__all__ = ["Finding", "Side", "compare"]


@dataclass(frozen=True)
class Finding:
    """`kind` is missing | extra | required | type | unresolvable, and
    `field` is rooted at `body`, `query` or `response`."""

    kind: str
    field: str
    detail: str = ""


@dataclass(frozen=True)
class Side:
    """A schema and the document its `$ref`s resolve in."""

    root: dict[str, Any]
    schema: Any

    def at(self, schema: Any) -> Side:
        return Side(self.root, schema)


@dataclass(frozen=True)
class Branch:
    side: Side
    origin: int
    discriminator: str | None


def _branches(side: Side, discriminator: str | None = None) -> list[Branch]:
    schema = deref(side.root, side.schema)
    if len(schema.get("allOf") or []) == 1:
        return _branches(side.at(schema["allOf"][0]), discriminator)
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    own = (schema.get("discriminator") or {}).get("propertyName")
    if alternatives:
        return [
            b
            for alt in alternatives
            for b in _branches(side.at(alt), own or discriminator)
        ]
    kinds = schema.get("type")
    if isinstance(kinds, list):
        return [
            Branch(side.at({**schema, "type": t}), id(schema), discriminator)
            for t in kinds
            if t != "null"
        ]
    if kinds == "null":
        return []
    return [Branch(side.at(schema), id(schema), discriminator)]


def kind_of(schema: dict[str, Any]) -> str:
    kind = schema.get("type")
    if kind in ("integer", "number"):
        return "number"
    if isinstance(kind, str):
        return kind
    if "properties" in schema or "additionalProperties" in schema:
        return "object"
    values = schema.get("enum") or (
        [schema["const"]] if "const" in schema else []
    )
    if values:
        return {str: "string", bool: "boolean", int: "number"}.get(
            type(values[0]), "any"
        )
    return "any"


def _kinds(branches: list[Branch]) -> set[str]:
    return {kind_of(b.side.schema) for b in branches}


def _named(b: Branch) -> bool:
    return kind_of(b.side.schema) == "object" and bool(
        b.side.schema.get("properties")
    )


@dataclass
class Comparison:
    out: list[Finding] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def add(self, kind: str, at: str, detail: str = "") -> None:
        self.out.append(Finding(kind, at, detail))


def compare(
    ref: Side, sdk: Side, at: str, *, repeatable: bool = False
) -> list[Finding]:
    """Findings for the SDK schema against the reference schema."""
    run = Comparison()
    _compare(run, ref, sdk, at, repeatable)
    return run.out


def _compare(
    run: Comparison, ref: Side, sdk: Side, at: str, repeatable: bool
) -> None:
    refs, sdks = _branches(ref), _branches(sdk)
    if not refs or not sdks:
        return
    ref_kinds, sdk_kinds = _kinds(refs), _kinds(sdks)
    if "any" in ref_kinds:
        return
    # A field the SDK leaves untyped compares nothing, so it is named
    # rather than passed.
    if "any" in sdk_kinds:
        run.add("unresolvable", at, "untyped")
        return
    # A query string repeats a key for a list, so one scalar value is a
    # list of one and matches an array parameter.
    if repeatable and "array" in ref_kinds and "array" not in sdk_kinds:
        items = [b for b in refs if kind_of(b.side.schema) == "array"]
        _compare(
            run,
            items[0].side.at(items[0].side.schema.get("items")),
            sdk,
            at,
            False,
        )
        return
    if not ref_kinds & sdk_kinds:
        run.add(
            "type",
            at,
            f"reference {' | '.join(sorted(ref_kinds))}, "
            f"SDK {' | '.join(sorted(sdk_kinds))}",
        )
        return
    if "array" in ref_kinds & sdk_kinds:
        _compare_items(run, refs, sdks, at)
    if "object" in ref_kinds & sdk_kinds:
        _compare_object_branches(run, refs, sdks, at)


def _items(branches: list[Branch]) -> list[Side]:
    return [
        b.side.at(b.side.schema["items"])
        for b in branches
        if kind_of(b.side.schema) == "array" and "items" in b.side.schema
    ]


def _compare_items(
    run: Comparison, refs: list[Branch], sdks: list[Branch], at: str
) -> None:
    ref_items, sdk_items = _items(refs), _items(sdks)
    if len(ref_items) == 1 and len(sdk_items) == 1:
        _compare(run, ref_items[0], sdk_items[0], f"{at}[]", False)


def _compare_object_branches(
    run: Comparison, refs: list[Branch], sdks: list[Branch], at: str
) -> None:
    ref_objects = [b for b in refs if _named(b)]
    sdk_objects = [b for b in sdks if _named(b)]
    if not ref_objects:
        return
    if not sdk_objects:
        # The reference names fields the SDK types as `dict[str, ...]`.
        run.add("unresolvable", at, "no named fields")
        return
    # Keyed by identity, so two inline schemas that print the same still
    # each get their check, and mutually recursive schemas end.
    key = (
        "|".join(str(o) for o in sorted({b.origin for b in ref_objects}))
        + "::"
        + "|".join(str(o) for o in sorted({b.origin for b in sdk_objects}))
    )
    if key in run.seen:
        return
    run.seen.add(key)
    discriminator = ref_objects[0].discriminator
    if len(ref_objects) > 1 and discriminator:
        _compare_variants(run, ref_objects, sdk_objects, discriminator, at)
    else:
        _compare_objects(run, ref_objects, sdk_objects, at)


def _tags(b: Branch, name: str) -> list[Any]:
    prop = b.side.schema.get("properties", {}).get(name)
    if prop is None:
        return []
    return [
        v
        for p in _branches(b.side.at(prop))
        for v in p.side.schema.get("enum")
        or ([p.side.schema["const"]] if "const" in p.side.schema else [])
    ]


def _compare_variants(
    run: Comparison,
    refs: list[Branch],
    sdks: list[Branch],
    name: str,
    at: str,
) -> None:
    """A discriminated union, paired by discriminator value."""
    ref_by = {v: b for b in refs for v in _tags(b, name)}
    sdk_by = {v: b for b in sdks for v in _tags(b, name)}
    for value, ref in ref_by.items():
        where = f"{at}({name}={value})"
        if value not in sdk_by:
            run.add("missing", where, "variant")
        else:
            _compare_objects(run, [ref], [sdk_by[value]], where)
    for value in sdk_by.keys() - ref_by.keys():
        run.add("extra", f"{at}({name}={value})", "variant")


def _properties(branches: list[Branch]) -> tuple[dict[str, Side], set[str]]:
    """Fields across the branches, and the ones every branch requires."""
    props: dict[str, Side] = {}
    required: set[str] | None = None
    for b in branches:
        for name, prop in b.side.schema.get("properties", {}).items():
            props.setdefault(name, b.side.at(prop))
        own = set(b.side.schema.get("required") or ())
        required = own if required is None else required & own
    return props, required or set()


def _compare_objects(
    run: Comparison, refs: list[Branch], sdks: list[Branch], at: str
) -> None:
    """Field names, then required-ness, then each shared field. Only
    "required in the reference, optional in the SDK" is a mismatch: a field
    the SDK always sends or reads where the reference makes it optional is
    fine, and the reference marks every field with a default optional."""
    ref_props, ref_required = _properties(refs)
    sdk_props, sdk_required = _properties(sdks)
    query = at == "query"
    for name, ref in ref_props.items():
        child = f"{at}.{name}"
        sdk = sdk_props.get(name)
        if sdk is None:
            run.add("missing", child)
            continue
        if name in ref_required and name not in sdk_required:
            run.add(
                "required",
                child,
                "required in the reference, optional in the SDK",
            )
        _compare(run, ref, sdk, child, query)
    for name in sdk_props.keys() - ref_props.keys():
        run.add("extra", f"{at}.{name}")
