"""Tests for ``client.recipes`` (:mod:`introspection_sdk.resources.recipes`)."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.resources.recipes import Recipes

from .conftest import (
    PROJECT_ID,
    RECIPE_ID,
    REPOSITORY_ID,
    FakeAPI,
    paginated,
    recipe_payload,
)


def _recipes(fake_api: FakeAPI) -> Recipes:
    return Recipes(fake_api.client())


def test_list_serialises_uuid_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/recipes", json_body=paginated([recipe_payload()]))
    page = _recipes(fake_api).list(
        project=PROJECT_ID, repository_id=UUID(REPOSITORY_ID)
    )
    assert str(page.records[0].id) == RECIPE_ID
    params = fake_api.last_request.params
    assert params.get("project") == PROJECT_ID
    assert params.get("repository_id") == REPOSITORY_ID


def test_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/recipes", json_body=paginated([recipe_payload()]))
    assert len(list(_recipes(fake_api).list(project=PROJECT_ID))) == 1


def test_get(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/recipes/{RECIPE_ID}", json_body=recipe_payload())
    recipe = _recipes(fake_api).get(UUID(RECIPE_ID))
    assert recipe.slug == "default"
