"""Strict decoding (``INTROSPECTION_STRICT_SCHEMA=1``): a response field no
model names fails the read with its JSON path; off, it is tolerated."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, Field

from introspection_sdk import IntrospectionAPIError, SchemaDriftError
from introspection_sdk._strict_schema import STRICT_SCHEMA_ENV, unmodelled
from introspection_sdk.resources.api_keys import ApiKeys
from introspection_sdk.resources.recipes import AsyncRecipes, Recipes
from introspection_sdk.runner_resources import Conversations
from introspection_sdk.schemas.genai_span import GenAiSpanList

from .conftest import (
    PROJECT_ID,
    RECIPE_ID,
    FakeAPI,
    recipe_payload,
    to_jsonable,
)
from .test_project_admin import api_key_payload


def _recipe(**extra: Any) -> dict[str, Any]:
    return {**to_jsonable(recipe_payload()), **extra}


def _span(**introspection: Any) -> dict[str, Any]:
    return {
        "trace_id": "trace-1",
        "span_id": "span-1",
        "start_time": "2026-11-05T10:00:00Z",
        # Open by design: a dict field, a customer attribute family, and a
        # gen_ai.* key the SDK does not type.
        "resource": {"service.name": "agent", "host": {"arch": "arm64"}},
        "attributes": {
            "acme": {"tenant": "t-1"},
            "gen_ai": {
                "operation": {"name": "chat", "acme_flag": True},
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "parts": [{"type": "text", "content": "hi"}],
                            "provider_extra": 1,
                        }
                    ]
                },
            },
            "introspection": {"turn": 1, **introspection},
        },
    }


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STRICT_SCHEMA_ENV, "1")


def test_off_by_default_tolerates_an_unknown_field(
    fake_api: FakeAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(STRICT_SCHEMA_ENV, raising=False)
    fake_api.add(
        "GET", f"/v1/recipes/{RECIPE_ID}", json_body=_recipe(color="red")
    )

    recipe = Recipes(fake_api.client()).get(UUID(RECIPE_ID))

    assert recipe.model_extra == {"color": "red"}


@pytest.mark.usefixtures("strict")
def test_strict_names_the_route_and_every_unmodelled_path(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/recipes",
        json_body={
            "records": [_recipe(), _recipe(color="red")],
            "count": 2,
            "cursor_v2": "c",
        },
    )

    with pytest.raises(SchemaDriftError) as caught:
        Recipes(fake_api.client()).list(project=PROJECT_ID).first_page()

    error = caught.value
    assert str(error) == (
        "/v1/recipes: response fields this SDK does not model: "
        "$.records[1].color, $.cursor_v2"
    )
    assert error.path == "/v1/recipes"
    assert error.fields == ["$.records[1].color", "$.cursor_v2"]
    assert isinstance(error, IntrospectionAPIError)
    assert error.code == "schema_drift"


@pytest.mark.usefixtures("strict")
def test_strict_reports_a_nested_field_and_leaves_open_maps_alone(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/export",
        json_body={
            "object": "list",
            "data": [_span(), _span(tool_response_ids=["call-1"], novel=1)],
        },
    )

    with pytest.raises(SchemaDriftError) as caught:
        Conversations(fake_api.client()).export_json("conv-1")

    assert caught.value.fields == ["$.data[1].attributes.introspection.novel"]


@pytest.mark.usefixtures("strict")
def test_strict_passes_a_fully_modelled_response(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/conversations/conv-1/export",
        json_body={
            "object": "list",
            "data": [_span(tool_call_ids=["call-1"], byok=False)],
        },
    )

    spans = Conversations(fake_api.client()).export_json("conv-1")

    assert spans.data[0].attributes.introspection is not None
    assert spans.data[0].attributes.introspection.tool_call_ids == ["call-1"]


@pytest.mark.usefixtures("strict")
def test_strict_paths_an_item_cut_from_a_larger_body(fake_api: FakeAPI):
    key = api_key_payload()
    fake_api.add(
        "GET", "/v1/api-keys", json_body={"api_keys": [key, {**key, "x": 1}]}
    )

    with pytest.raises(SchemaDriftError) as caught:
        ApiKeys(fake_api.client()).list(project=PROJECT_ID)

    assert "$.api_keys[1].x" in caught.value.fields


@pytest.mark.usefixtures("strict")
async def test_strict_covers_the_async_twin(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/recipes/{RECIPE_ID}", json_body=_recipe(color="red")
    )

    with pytest.raises(SchemaDriftError) as caught:
        await AsyncRecipes(fake_api.async_client()).get(UUID(RECIPE_ID))

    assert caught.value.fields == ["$.color"]


def test_unmodelled_follows_dicts_of_models_and_ignores_open_dicts():
    payload = {
        "object": "list",
        "data": [_span(novel=1)],
        "first_id": "span-1",
    }
    spans = GenAiSpanList.model_validate(payload)

    assert unmodelled(spans, payload) == [
        "$.data[0].attributes.introspection.novel"
    ]
    assert unmodelled({"a": spans}, {"a": payload}) == [
        "$.a.data[0].attributes.introspection.novel"
    ]


class Aliased(BaseModel):
    camel: int = Field(alias="camelCase")
    either: int = Field(
        validation_alias=AliasChoices("one", AliasPath("two", 0))
    )


def test_unmodelled_matches_keys_by_alias():
    for payload in (
        {"camelCase": 1, "one": 2},
        {"camelCase": 1, "two": [2]},
    ):
        assert unmodelled(Aliased.model_validate(payload), payload) == []
    payload = {"camelCase": 1, "one": 2, "three": 3}
    assert unmodelled(Aliased.model_validate(payload), payload) == ["$.three"]
