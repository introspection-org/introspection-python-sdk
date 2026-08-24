"""Contract tests for runner-bound annotation datasets."""

from __future__ import annotations

from typing import Any

from introspection_sdk.runner_resources.datasets import (
    AsyncDatasets,
    Datasets,
)
from introspection_sdk.schemas.datasets import Dataset

from .conftest import FakeAPI, paginated

DATASET_ID = "ddddddd1-dddd-dddd-dddd-dddddddddddd"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"


def dataset_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": DATASET_ID,
        "org_id": "00000000-0000-0000-0000-0000000000aa",
        "project_id": "00000000-0000-0000-0000-0000000000bb",
        "slug": "golden-set",
        "description": "Curated review conversations",
        "created_by_member_id": MEMBER_ID,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(over)
    return payload


def test_datasets_create_and_list(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/datasets", json_body=dataset_payload())
    fake_api.add(
        "GET",
        "/v1/datasets",
        json_body=paginated([Dataset.model_validate(dataset_payload())]),
    )
    datasets = Datasets(fake_api.client())

    created = datasets.create(
        slug="golden-set",
        description="Curated review conversations",
    )
    assert created.slug == "golden-set"
    assert fake_api.last_request.json() == {
        "slug": "golden-set",
        "description": "Curated review conversations",
    }

    listed = datasets.list(slug="golden-set", created_by_member_id=MEMBER_ID)
    assert str(listed.records[0].created_by_member_id) == MEMBER_ID
    params = fake_api.last_request.params
    assert params["slug"] == "golden-set"
    assert params["created_by_member_id"] == MEMBER_ID


def test_datasets_create_omits_missing_description(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/datasets",
        json_body=dataset_payload(description=None),
    )
    Datasets(fake_api.client()).create(slug="golden-set")
    # No description at all must not smuggle a null onto the wire.
    assert fake_api.last_request.json() == {"slug": "golden-set"}


def test_datasets_get_update_delete(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/datasets/{DATASET_ID}", json_body=dataset_payload()
    )
    fake_api.add(
        "PATCH",
        f"/v1/datasets/{DATASET_ID}",
        json_body=dataset_payload(description="renamed"),
    )
    fake_api.add("DELETE", f"/v1/datasets/{DATASET_ID}", status=204)
    datasets = Datasets(fake_api.client())

    got = datasets.get(DATASET_ID)
    assert str(got.id) == DATASET_ID

    updated = datasets.update(DATASET_ID, description="renamed")
    assert updated.description == "renamed"
    assert fake_api.last_request.json() == {"description": "renamed"}

    datasets.delete(DATASET_ID)
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.path == f"/v1/datasets/{DATASET_ID}"


async def test_async_datasets_create(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/datasets", json_body=dataset_payload())
    created = await AsyncDatasets(fake_api.async_client()).create(
        slug="golden-set",
        description="Curated review conversations",
    )
    assert created.slug == "golden-set"
    assert fake_api.last_request.json() == {
        "slug": "golden-set",
        "description": "Curated review conversations",
    }
