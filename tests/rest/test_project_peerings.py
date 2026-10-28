"""Contract tests for ``projects.peerings``, the read-only runtime peerings.

Each pins the path under ``/v1/projects/{project}``, the ``runtime`` and
``granted`` selectors, paging, and that a peering outside the project is a
typed 404. The namespace has no write methods by design.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest

from introspection_sdk import IntrospectionClient
from introspection_sdk._errors import NotFoundError, ValidationError
from introspection_sdk.resources import (
    AsyncProjectPeerings,
    ProjectPeerings,
)

from .conftest import MEMBER_ID, ORG_ID, PROJECT_ID, RUNTIME_GROUP_ID, FakeAPI

NOW = "2026-10-28T12:00:00Z"
PEERING_ID = "0199a1b2-0000-7000-8000-0000000000b1"
OTHER_PEERING_ID = "0199a1b2-0000-7000-8000-0000000000b2"
GRANTED_ORG_ID = "0199a1b2-0000-7000-8000-0000000000b3"
DEPLOYMENT_ID = "0199a1b2-0000-7000-8000-0000000000b4"
PEERINGS = f"/v1/projects/{PROJECT_ID}/peerings"


def page(*records: dict[str, Any], next: str | None = None) -> dict:
    return {"records": list(records), "count": len(records), "next": next}


def peering_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": PEERING_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "granted_org_id": GRANTED_ORG_ID,
        "granted_project_id": None,
        "granted_deployment_id": DEPLOYMENT_ID,
        "expires_at": None,
        "created_by_member_id": MEMBER_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
        **over,
    }


def test_client_hangs_peerings_off_projects_on_the_control_plane():
    client = IntrospectionClient(
        token="t",
        base_api_url="https://cp.test",
        dp_url="https://dp.test",
    )
    try:
        assert client.projects.peerings._http is client._http
    finally:
        client.shutdown()


def test_peerings_namespace_is_read_only():
    public = {n for n in dir(ProjectPeerings) if not n.startswith("_")}
    assert public == {"list", "get"}


def test_list_sends_runtime_and_parses_the_record(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/projects/support/peerings",
        json_body=page(peering_payload()),
    )

    (peering,) = ProjectPeerings(fake_api.client()).list("support", "agent")

    assert peering.id == UUID(PEERING_ID)
    assert peering.runtime_group_id == UUID(RUNTIME_GROUP_ID)
    assert peering.granted_org_id == UUID(GRANTED_ORG_ID)
    assert peering.granted_project_id is None
    assert peering.granted_deployment_id == UUID(DEPLOYMENT_ID)
    assert peering.created_by_member_id == UUID(MEMBER_ID)
    assert peering.expires_at is None
    assert dict(fake_api.last_request.params) == {"runtime": "agent"}


def test_list_by_ids_and_without_filters_sends_none(fake_api: FakeAPI):
    fake_api.add("GET", PEERINGS, json_body=page())

    peerings = ProjectPeerings(fake_api.client())
    assert list(peerings.list(UUID(PROJECT_ID))) == []
    assert dict(fake_api.last_request.params) == {}

    list(peerings.list(UUID(PROJECT_ID), UUID(RUNTIME_GROUP_ID)))
    assert dict(fake_api.last_request.params) == {"runtime": RUNTIME_GROUP_ID}


def test_list_granted_sends_the_flag(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        PEERINGS,
        json_body=page(peering_payload(org_id=GRANTED_ORG_ID)),
    )

    (peering,) = ProjectPeerings(fake_api.client()).list(
        PROJECT_ID, granted=True, limit=10
    )

    assert peering.org_id == UUID(GRANTED_ORG_ID)
    assert dict(fake_api.last_request.params) == {
        "granted": "true",
        "limit": "10",
    }


def test_list_granted_with_runtime_surfaces_the_422(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        PEERINGS,
        status=422,
        json_body={"detail": "runtime cannot be combined with granted"},
    )

    with pytest.raises(ValidationError):
        ProjectPeerings(fake_api.client()).list(
            PROJECT_ID, "agent", granted=True
        ).page()


def test_list_follows_the_cursor(fake_api: FakeAPI):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("next") == "c2":
            body = page(peering_payload(id=OTHER_PEERING_ID))
        else:
            body = page(peering_payload(), next="c2")
        return httpx.Response(200, json=body)

    fake_api.add_handler("GET", PEERINGS, handler)

    ids = [p.id for p in ProjectPeerings(fake_api.client()).list(PROJECT_ID)]

    assert ids == [UUID(PEERING_ID), UUID(OTHER_PEERING_ID)]
    first, second = fake_api.requests
    assert "next" not in first.params
    assert second.params.get("next") == "c2"


def test_get_reads_one_and_percent_encodes_the_slug(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/projects/acme/support desk/peerings/{PEERING_ID}",
        json_body=peering_payload(),
    )

    peering = ProjectPeerings(fake_api.client()).get(
        "acme/support desk", UUID(PEERING_ID)
    )

    assert peering.id == UUID(PEERING_ID)
    assert fake_api.last_request.url.raw_path == (
        f"/v1/projects/acme%2Fsupport%20desk/peerings/{PEERING_ID}".encode()
    )


def test_get_outside_the_project_is_typed(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        ProjectPeerings(fake_api.client()).get(PROJECT_ID, PEERING_ID)


async def test_async_list_and_get(fake_api: FakeAPI):
    fake_api.add("GET", PEERINGS, json_body=page(peering_payload()))
    fake_api.add(
        "GET", f"{PEERINGS}/{PEERING_ID}", json_body=peering_payload()
    )
    peerings = AsyncProjectPeerings(fake_api.async_client())

    first = await peerings.list(PROJECT_ID, granted=True)
    streamed = [p.id async for p in peerings.list(PROJECT_ID, "agent")]
    one = await peerings.get(PROJECT_ID, UUID(PEERING_ID))

    assert [p.id for p in first.records] == [UUID(PEERING_ID)]
    assert streamed == [UUID(PEERING_ID)]
    assert one.project_id == UUID(PROJECT_ID)
    assert dict(fake_api.requests[0].params) == {"granted": "true"}
    assert dict(fake_api.requests[1].params) == {"runtime": "agent"}
