"""Tests for ``client.recipes`` (:mod:`introspection_sdk.resources.recipes`)."""

from __future__ import annotations

from uuid import UUID

import pytest

from introspection_sdk._errors import NotFoundError
from introspection_sdk.resources.recipes import AsyncRecipes, Recipes

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


def test_create_pins_a_commit(fake_api: FakeAPI):
    sha = "a" * 40
    fake_api.add(
        "POST",
        "/v1/recipes",
        status=201,
        json_body=recipe_payload(git_commit_sha=sha),
    )
    recipe = _recipes(fake_api).create(
        project=UUID(PROJECT_ID),
        repository_id=UUID(REPOSITORY_ID),
        name="default",
        git_ref="main",
        git_commit_sha=sha,
    )
    assert recipe.git_commit_sha == sha
    assert fake_api.last_request.json() == {
        "project": PROJECT_ID,
        "repository_id": REPOSITORY_ID,
        "name": "default",
        "git_ref": "main",
        "git_commit_sha": sha,
    }


def test_update_and_delete(fake_api: FakeAPI):
    path = f"/v1/recipes/{RECIPE_ID}"
    fake_api.add("PATCH", path, json_body=recipe_payload(description="d"))
    fake_api.add("DELETE", path, status=204)
    recipes = _recipes(fake_api)
    assert recipes.update(RECIPE_ID, description="d").description == "d"
    assert fake_api.last_request.json() == {"description": "d"}
    recipes.delete(RECIPE_ID, project=PROJECT_ID)
    assert fake_api.last_request.params.get("project") == PROJECT_ID


def test_delete_a_missing_recipe(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        _recipes(fake_api).delete(RECIPE_ID)


async def test_async_recipe_writes(fake_api: FakeAPI):
    path = f"/v1/recipes/{RECIPE_ID}"
    fake_api.add("POST", "/v1/recipes", status=201, json_body=recipe_payload())
    fake_api.add("PATCH", path, json_body=recipe_payload(name="renamed"))
    fake_api.add("DELETE", path, status=204)
    recipes = AsyncRecipes(fake_api.async_client())
    await recipes.create(
        project="support", repository_id=REPOSITORY_ID, name="default"
    )
    assert fake_api.last_request.json()["project"] == "support"
    updated = await recipes.update(
        RECIPE_ID, project="support", name="renamed"
    )
    assert updated.name == "renamed"
    await recipes.delete(RECIPE_ID)
    assert fake_api.last_request.method == "DELETE"
