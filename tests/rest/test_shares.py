"""Contract tests for runner-bound sharing grants."""

from __future__ import annotations

from introspection_sdk.runner_resources.shares import AsyncShares, Shares
from introspection_sdk.schemas.shares import (
    ResourceShare,
    ShareCreateRequest,
    ShareResourceType,
)

from .conftest import FakeAPI, paginated

SHARE_ID = "77777777-7777-7777-7777-777777777777"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"


def share_payload() -> dict[str, object]:
    return {
        "id": SHARE_ID,
        "org_id": "00000000-0000-0000-0000-0000000000aa",
        "project_id": "00000000-0000-0000-0000-0000000000bb",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "resource_type": "file",
        "resource_id": "file-1",
        "granted_member_id": MEMBER_ID,
        "created_by_member_id": MEMBER_ID,
        "url": "https://example.test/share",
    }


def test_shares_create_member_grant_and_list(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/shares", json_body=share_payload())
    fake_api.add(
        "GET",
        "/v1/shares",
        json_body=paginated([ResourceShare.model_validate(share_payload())]),
    )
    shares = Shares(fake_api.client())

    created = shares.create(
        resource_type="file",
        resource_id="file-1",
        granted_member_id=MEMBER_ID,
    )
    assert str(created.granted_member_id) == MEMBER_ID
    assert fake_api.last_request.json() == {
        "resource_type": "file",
        "resource_id": "file-1",
        "granted_member_id": MEMBER_ID,
    }

    listed = shares.list(resource_id="file-1")
    assert str(listed.records[0].created_by_member_id) == MEMBER_ID


async def test_async_shares_create_member_grant(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/shares", json_body=share_payload())
    created = await AsyncShares(fake_api.async_client()).create(
        resource_type="file",
        resource_id="file-1",
        granted_member_id=MEMBER_ID,
    )
    assert created.url == "https://example.test/share"


def test_share_create_omits_the_target_for_a_project_wide_grant():
    body = ShareCreateRequest(
        resource_type=ShareResourceType.FILE,
        resource_id="file-1",
    ).model_dump(mode="json", exclude_none=True)

    # No target at all is the project-wide grant, and it must not smuggle a
    # null `granted_member_id` onto the wire.
    assert body == {"resource_type": "file", "resource_id": "file-1"}
