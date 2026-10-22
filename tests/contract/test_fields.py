"""The schema comparison on its own: both sides as JSON Schema."""

from __future__ import annotations

from api_contract.fields import Finding, Side, compare


def side(schema, defs=None):
    root = {"$defs": defs or {}, "components": {"schemas": defs or {}}}
    return Side(root, schema)


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
    }


STRING = {"type": "string"}
NULLABLE_STRING = {"anyOf": [STRING, {"type": "null"}]}


def test_nullability_is_not_compared():
    assert (
        compare(
            side(obj({"a": NULLABLE_STRING})), side(obj({"a": STRING})), "body"
        )
        == []
    )


def test_optional_in_reference_and_required_in_sdk_passes():
    assert (
        compare(
            side(obj({"a": STRING})),
            side(obj({"a": STRING}, ["a"])),
            "response",
        )
        == []
    )


def test_integer_and_number_are_one_basic_type():
    assert (
        compare(side({"type": "number"}), side({"type": "integer"}), "body")
        == []
    )


def test_refs_are_followed_on_both_sides():
    ref = side(
        obj({"inner": {"$ref": "#/components/schemas/Inner"}}),
        {"Inner": obj({"x": STRING, "y": STRING})},
    )
    sdk = side(
        obj({"inner": {"$ref": "#/$defs/Inner"}}),
        {"Inner": obj({"x": {"type": "boolean"}})},
    )

    assert set(compare(ref, sdk, "body")) == {
        Finding("missing", "body.inner.y"),
        Finding("type", "body.inner.x", "reference string, SDK boolean"),
    }


def test_recursive_schemas_end():
    defs = {"Node": obj({"next": {"$ref": "#/$defs/Node"}, "v": STRING})}
    ref = side({"$ref": "#/$defs/Node"}, defs)

    assert compare(ref, side({"$ref": "#/$defs/Node"}, defs), "response") == []


def test_one_query_value_matches_an_array_parameter():
    ref = obj({"tags": {"type": "array", "items": STRING}})

    assert compare(side(ref), side(obj({"tags": STRING})), "query") == []


def test_untyped_and_unnamed_sdk_fields_are_unresolvable():
    ref = obj({"a": STRING, "b": obj({"x": STRING})})
    sdk = obj({"a": {}, "b": {"type": "object", "additionalProperties": True}})

    assert set(compare(side(ref), side(sdk), "body")) == {
        Finding("unresolvable", "body.a", "untyped"),
        Finding("unresolvable", "body.b", "no named fields"),
    }


def test_untyped_reference_field_compares_nothing():
    assert (
        compare(side(obj({"a": {}})), side(obj({"a": STRING})), "body") == []
    )


def test_discriminated_variants_pair_by_value():
    def variant(tag, extra):
        return obj(
            {"kind": {"const": tag, "type": "string"}, **extra}, ["kind"]
        )

    ref = side(
        {
            "oneOf": [variant("a", {"x": STRING}), variant("b", {})],
            "discriminator": {"propertyName": "kind"},
        }
    )
    sdk = side(
        {
            "oneOf": [variant("a", {}), variant("c", {})],
            "discriminator": {"propertyName": "kind"},
        }
    )

    assert set(compare(ref, sdk, "response")) == {
        Finding("missing", "response(kind=a).x"),
        Finding("missing", "response(kind=b)", "variant"),
        Finding("extra", "response(kind=c)", "variant"),
    }


def test_array_items_are_compared():
    ref = {"type": "array", "items": obj({"x": STRING}, ["x"])}
    sdk = {"type": "array", "items": obj({"x": STRING})}

    assert compare(side(ref), side(sdk), "response") == [
        Finding(
            "required",
            "response[].x",
            "required in the reference, optional in the SDK",
        )
    ]


def mapping(values):
    return {"type": "object", "additionalProperties": values}


def test_typed_dictionary_values_are_compared():
    ref = obj({"labels": mapping({"type": "integer"})})

    assert compare(
        side(ref), side(obj({"labels": mapping(STRING)})), "body"
    ) == [Finding("type", "body.labels{}", "reference number, SDK string")]


def test_models_behind_dictionary_values_are_compared():
    ref = obj({"by_id": mapping(obj({"x": STRING, "y": STRING}))})
    sdk = obj({"by_id": mapping(obj({"x": STRING}))})

    assert compare(side(ref), side(sdk), "response") == [
        Finding("missing", "response.by_id{}.y")
    ]


def test_untyped_dictionary_against_typed_values_is_unresolvable():
    ref = obj({"labels": mapping(STRING)})
    sdk = obj({"labels": mapping(True)})

    assert compare(side(ref), side(sdk), "body") == [
        Finding("unresolvable", "body.labels{}", "untyped")
    ]
    assert compare(side(sdk), side(ref), "body") == []


def test_recursive_dictionaries_end():
    defs = {"Tree": mapping({"$ref": "#/$defs/Tree"})}

    assert (
        compare(
            side(obj({"t": {"$ref": "#/$defs/Tree"}}), defs),
            side(obj({"t": {"$ref": "#/$defs/Tree"}}), defs),
            "body",
        )
        == []
    )


SCALARS = {
    "anyOf": [
        STRING,
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
    ]
}


def test_sdk_sending_a_type_the_reference_does_not_accept_is_a_mismatch():
    assert compare(
        side(obj({"v": NULLABLE_STRING})), side(obj({"v": SCALARS})), "body"
    ) == [
        Finding(
            "type", "body.v", "reference string, SDK boolean | number | string"
        )
    ]


def test_sdk_sending_a_narrower_union_passes():
    assert (
        compare(side(obj({"v": SCALARS})), side(obj({"v": STRING})), "body")
        == []
    )


def test_response_the_sdk_cannot_read_is_a_mismatch():
    ref, sdk = side(obj({"v": SCALARS})), side(obj({"v": NULLABLE_STRING}))

    assert compare(ref, sdk, "response") == [
        Finding(
            "type",
            "response.v",
            "reference boolean | number | string, SDK string",
        )
    ]
    assert compare(sdk, ref, "response") == []


def test_one_query_value_still_matches_a_union_array_parameter():
    ref = obj(
        {
            "tags": {
                "anyOf": [{"type": "array", "items": STRING}, {"type": "null"}]
            }
        }
    )

    assert compare(side(ref), side(obj({"tags": STRING})), "query") == []
