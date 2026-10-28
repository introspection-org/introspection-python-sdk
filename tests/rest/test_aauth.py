"""Contract tests for ``client.aauth`` (DP ``/v1/aauth/missions`` and
``/v1/aauth/approvals``)."""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk._errors import NotFoundError
from introspection_sdk.runner_resources import AAuth, AsyncAAuth
from introspection_sdk.schemas.aauth import ApprovalKind, ApprovalStatus

from .conftest import MEMBER_ID, ORG_ID, PROJECT_ID, FakeAPI

MISSION_ID = "0199a1b2-0000-7000-8000-0000000000f1"
NOW = "2026-10-21T12:00:00Z"

MISSION = {
    "id": MISSION_ID,
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "s256": "hash",
    "mission": "Book the team offsite",
    "agent_id": "aauth:agent@example.com",
    "member_id": MEMBER_ID,
    "resources": ["https://calendar.example"],
    "budget": {"amount": 50000, "unit": "USD", "decimals": 2},
    "spent": 0,
    "log": [{"at": NOW, "entry": "approved"}],
    "expires_at": NOW,
    "completed_at": None,
    "created_at": NOW,
    "updated_at": NOW,
}

APPROVAL = {
    "id": "0199a1b2-0000-7000-8000-0000000000f2",
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "kind": "mission",
    "status": "pending",
    "agent_id": "aauth:agent@example.com",
    "member_id": MEMBER_ID,
    "mission_id": MISSION_ID,
    "description": "Book the team offsite",
    "expires_at": NOW,
    "created_at": NOW,
    "updated_at": NOW,
}


def page(*records: dict[str, Any], next: str | None = None) -> dict[str, Any]:
    return {"records": list(records), "count": len(records), "next": next}


def test_missions_list(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/aauth/missions", json_body=page(MISSION))
    missions = AAuth(fake_api.client()).missions.list(member_id=MEMBER_ID)
    first = missions.page().records[0]
    assert first.budget is not None and first.budget.amount == 50000
    assert first.log[0].entry == "approved"
    assert fake_api.last_request.params.get("member_id") == MEMBER_ID


def test_approvals_list_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/aauth/approvals", json_body=page(APPROVAL))
    approvals = AAuth(fake_api.client()).approvals.list(
        status=[ApprovalStatus.PENDING, "approved"],
        kind=ApprovalKind.MISSION,
        mission_id=MISSION_ID,
    )
    first = next(iter(approvals))
    assert first.kind == ApprovalKind.MISSION
    assert first.status == ApprovalStatus.PENDING
    params = fake_api.last_request.params
    assert params.get_list("status") == ["pending", "approved"]
    assert params.get("kind") == "mission"
    assert params.get("mission_id") == MISSION_ID
    assert "member_id" not in params


def test_a_plane_without_aauth(fake_api: FakeAPI):
    with pytest.raises(NotFoundError):
        AAuth(fake_api.client()).missions.list().page()


async def test_async_aauth_reads_empty(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/aauth/missions", json_body=page())
    fake_api.add("GET", "/v1/aauth/approvals", json_body=page())
    aauth = AsyncAAuth(fake_api.async_client())
    assert (await aauth.missions.list(limit=5)).records == []
    assert fake_api.last_request.params.get("limit") == "5"
    assert [a async for a in aauth.approvals.list()] == []
