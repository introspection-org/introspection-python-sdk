"""Contract tests for the Control Plane writes an owner makes around a
project: ``projects`` create / update / delete, ``tokens.create`` and
``organizations.me``."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from introspection_sdk._errors import NotFoundError, ValidationError
from introspection_sdk.resources import (
    AsyncOrganizations,
    AsyncProjects,
    AsyncTokens,
    Organizations,
    Projects,
    Tokens,
)

from .conftest import MEMBER_ID, ORG_ID, PROJECT_ID, FakeAPI

DEPLOYMENT_ID = "0199a1b2-0000-7000-8000-0000000000d1"


def project(**over: Any) -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "org_id": ORG_ID,
        "deployment_id": DEPLOYMENT_ID,
        "name": "Support",
        "slug": "support",
        "description": None,
        "settings": None,
        "created_by_member_id": MEMBER_ID,
        **over,
    }


TOKEN = {
    "access_token": "eyJ.member.token",
    "token_type": "bearer",
    "expires_at": "2026-10-29T12:00:00Z",
    "project_id": PROJECT_ID,
    "org_id": ORG_ID,
    "refresh_token": None,
}

ORGANIZATION = {
    "id": ORG_ID,
    "name": "Acme",
    "slug": "acme",
    "external_org_id": "org_123",
    "image_url": None,
    "hosted_git": True,
}


def test_create_sends_only_the_fields_given(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/projects", status=201, json_body=project())
    created = Projects(fake_api.client()).create(
        name="Support", deployment_id=UUID(DEPLOYMENT_ID), slug="support"
    )
    assert str(created.deployment_id) == DEPLOYMENT_ID
    assert fake_api.last_request.json() == {
        "name": "Support",
        "deployment_id": DEPLOYMENT_ID,
        "slug": "support",
    }


def test_update_addresses_the_project_by_slug(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        "/v1/projects/support",
        json_body=project(description="Where support runs"),
    )
    updated = Projects(fake_api.client()).update(
        "support", description="Where support runs"
    )
    assert updated.description == "Where support runs"
    assert fake_api.last_request.json() == {
        "description": "Where support runs"
    }


def test_update_keeps_an_empty_description(fake_api: FakeAPI):
    # An empty string clears the description; only `None` is left unsent.
    fake_api.add("PATCH", f"/v1/projects/{PROJECT_ID}", json_body=project())
    Projects(fake_api.client()).update(UUID(PROJECT_ID), description="")
    assert fake_api.last_request.json() == {"description": ""}


def test_update_with_no_fields_is_a_400(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        "/v1/projects/support",
        status=400,
        json_body={"detail": "No fields to update"},
    )
    with pytest.raises(ValidationError):
        Projects(fake_api.client()).update("support")
    assert fake_api.last_request.json() == {}


def test_delete_and_a_missing_project(fake_api: FakeAPI):
    fake_api.add("DELETE", "/v1/projects/support", status=204)
    projects = Projects(fake_api.client())
    projects.delete("support")
    assert fake_api.last_request.method == "DELETE"
    with pytest.raises(NotFoundError):
        projects.delete("gone")


async def test_async_project_writes(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/projects", status=201, json_body=project())
    fake_api.add("PATCH", "/v1/projects/support", json_body=project())
    fake_api.add("DELETE", "/v1/projects/support", status=204)
    projects = AsyncProjects(fake_api.async_client())
    created = await projects.create(
        name="Support", deployment_id=DEPLOYMENT_ID, include_ark=False
    )
    assert created.slug == "support"
    assert fake_api.requests[-1].json()["include_ark"] is False
    await projects.update("support", name="Support desk")
    assert fake_api.requests[-1].json() == {"name": "Support desk"}
    await projects.delete("support")
    assert fake_api.last_request.method == "DELETE"


def test_token_create_returns_a_secret(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/tokens", json_body=TOKEN)
    minted = Tokens(fake_api.client()).create(
        project=UUID(PROJECT_ID), expires_hours=24
    )
    assert fake_api.last_request.json() == {
        "project": PROJECT_ID,
        "expires_hours": 24,
    }
    assert minted.access_token.get_secret_value() == "eyJ.member.token"
    assert "eyJ" not in repr(minted)
    assert str(minted.project_id) == PROJECT_ID


async def test_async_token_create(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/tokens",
        json_body={**TOKEN, "refresh_token": "refresh-me"},
    )
    minted = await AsyncTokens(fake_api.async_client()).create(
        project="support", include_refresh_token=True, environment="staging"
    )
    assert fake_api.last_request.json() == {
        "project": "support",
        "include_refresh_token": True,
        "environment": "staging",
    }
    assert minted.refresh_token is not None
    assert minted.refresh_token.get_secret_value() == "refresh-me"


def test_organization_me(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/organizations/me", json_body=ORGANIZATION)
    org = Organizations(fake_api.client()).me()
    assert (org.slug, org.hosted_git) == ("acme", True)


async def test_async_organization_me(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        await AsyncOrganizations(fake_api.async_client()).me()
    fake_api.add("GET", "/v1/organizations/me", json_body=ORGANIZATION)
    org = await AsyncOrganizations(fake_api.async_client()).me()
    assert org.external_org_id == "org_123"
