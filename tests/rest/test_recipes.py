"""Tests for ``client.recipes`` (:mod:`introspection_sdk.resources.recipes`)."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.resources.recipes import Recipes
from introspection_sdk.schemas.recipes import RecipeCreate

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


def test_create_from_model(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/recipes", json_body=recipe_payload())
    _recipes(fake_api).create(
        RecipeCreate(
            project=PROJECT_ID,
            repository_id=UUID(REPOSITORY_ID),
            name="default",
            git_ref="main",
            git_commit_sha="abc123",
        )
    )
    body = fake_api.last_request.json()
    assert body["project"] == PROJECT_ID
    assert body["git_ref"] == "main"
    assert "description" not in body


def test_create_from_dict(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/recipes", json_body=recipe_payload())
    _recipes(fake_api).create({"name": "default", "slug": None})
    assert "slug" not in fake_api.last_request.json()


def test_update(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/recipes/{RECIPE_ID}",
        json_body=recipe_payload(description="new"),
    )
    recipe = _recipes(fake_api).update(UUID(RECIPE_ID), {"description": "new"})
    assert recipe.description == "new"


def test_delete(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/recipes/{RECIPE_ID}", status=204)
    assert _recipes(fake_api).delete(UUID(RECIPE_ID)) is None
