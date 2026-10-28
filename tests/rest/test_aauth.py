"""Contract tests for ``client.aauth`` (DP ``/v1/aauth/missions`` and
``/v1/aauth/approvals``)."""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk._errors import NotFoundError
from introspection_sdk.runner_resources import AAuth, AsyncAAuth
from introspection_sdk.schemas.aauth import (
    ApprovalKind,
    ApprovalStatus,
    Budget,
)

from .conftest import MEMBER_ID, ORG_ID, PROJECT_ID, FakeAPI

MISSION_ID = "0199a1b2-0000-7000-8000-0000000000f1"
APPROVAL_ID = "0199a1b2-0000-7000-8000-0000000000f2"
TOKEN_APPROVAL_ID = "0199a1b2-0000-7000-8000-0000000000f3"
NOW = "2026-10-21T12:00:00+00:00"

# Each body is what the Data Plane's own `Mission` / `Approval` models
# (introspection-cloud apps/dataplane-api/.../models/person_server.py)
# serialize for a populated row: every field they emit, `+00:00`
# timestamps, and none of the fields they exclude (`agent_jkt`,
# `grant_claims`, `collected`, ...).
MISSION = {
    "id": MISSION_ID,
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "s256": "n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg",
    "mission": "Book the team offsite",
    "agent_id": "aauth:agent@example.com",
    "member_id": MEMBER_ID,
    "resources": ["https://calendar.example"],
    "budget": {"amount": 50000, "unit": "USD", "decimals": 2},
    "spent": 1250,
    "log": [{"at": NOW, "entry": "approved"}],
    "expires_at": NOW,
    "completed_at": None,
    "created_at": NOW,
    "updated_at": NOW,
}

APPROVAL = {
    "id": APPROVAL_ID,
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "kind": "mission",
    "status": "pending",
    "agent_id": "aauth:agent@example.com",
    "member_id": MEMBER_ID,
    "mission_id": MISSION_ID,
    "description": "Book the team offsite",
    "resource": None,
    "budget": {"amount": 50000, "unit": "USD", "decimals": 2},
    "summary": None,
    "decided_budget": None,
    "decided_by_member_id": None,
    "decided_at": None,
    "expires_at": NOW,
    "created_at": NOW,
    "updated_at": NOW,
}

# An auth-token approval the person decided, granting less than asked.
TOKEN_APPROVAL = {
    **APPROVAL,
    "id": TOKEN_APPROVAL_ID,
    "kind": "auth_token",
    "status": "approved",
    "description": "calendar:write for the offsite booking",
    "resource": "https://calendar.example",
    "budget": {"amount": 20000, "unit": "USD", "decimals": 2},
    "summary": "Reserve a room for 12 on 2026-11-04",
    "decided_budget": {"amount": 15000, "unit": "USD", "decimals": 2},
    "decided_by_member_id": MEMBER_ID,
    "decided_at": NOW,
}


def page(*records: dict[str, Any], next: str | None = None) -> dict[str, Any]:
    return {"records": list(records), "count": len(records), "next": next}


def test_missions_list(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/aauth/missions", json_body=page(MISSION, next="c2")
    )
    missions = AAuth(fake_api.client()).missions.list(
        member_id=MEMBER_ID, limit=1
    )
    first = missions.page().records[0]
    assert str(first.id) == MISSION_ID
    assert str(first.member_id) == MEMBER_ID
    assert first.mission == "Book the team offsite"
    assert first.resources == ["https://calendar.example"]
    assert first.budget == Budget(amount=50000, unit="USD", decimals=2)
    assert first.spent == 1250
    assert [(e.at, e.entry) for e in first.log] == [(NOW, "approved")]
    assert first.completed_at is None
    assert first.model_dump(mode="json") == MISSION
    request = fake_api.last_request
    assert (request.method, request.path) == ("GET", "/v1/aauth/missions")
    assert dict(request.params) == {"member_id": MEMBER_ID, "limit": "1"}


def test_approvals_list_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/aauth/approvals",
        json_body=page(APPROVAL, TOKEN_APPROVAL),
    )
    approvals = AAuth(fake_api.client()).approvals.list(
        status=[ApprovalStatus.PENDING, "approved"],
        kind=ApprovalKind.MISSION,
        mission_id=MISSION_ID,
    )
    pending, decided = list(approvals)
    assert pending.kind == ApprovalKind.MISSION
    assert pending.status == ApprovalStatus.PENDING
    assert str(pending.mission_id) == MISSION_ID
    assert pending.decided_at is None
    assert decided.kind == ApprovalKind.AUTH_TOKEN
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.resource == "https://calendar.example"
    assert decided.summary == "Reserve a room for 12 on 2026-11-04"
    assert decided.budget == Budget(amount=20000, unit="USD", decimals=2)
    assert decided.decided_budget == Budget(
        amount=15000, unit="USD", decimals=2
    )
    assert str(decided.decided_by_member_id) == MEMBER_ID
    assert decided.decided_at == NOW
    assert [a.model_dump(mode="json") for a in (pending, decided)] == [
        APPROVAL,
        TOKEN_APPROVAL,
    ]
    request = fake_api.last_request
    assert (request.method, request.path) == ("GET", "/v1/aauth/approvals")
    params = request.params
    assert params.get_list("status") == ["pending", "approved"]
    assert params.get("kind") == "mission"
    assert params.get("mission_id") == MISSION_ID
    assert "member_id" not in params
    assert "decided_by_member_id" not in params


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
