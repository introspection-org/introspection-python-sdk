"""Contract tests for runner-bound sharing grants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from introspection_sdk._errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from introspection_sdk.runner_resources.shares import AsyncShares, Shares
from introspection_sdk.schemas.shares import (
    ResourceShare,
    ShareCreateRequest,
    ShareResourceType,
    ShareUpdateRequest,
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


TAG = "team:acme"
CUTOFF = "2026-01-01T00:00:00Z"


def tag_share_payload(**overrides: object) -> dict[str, object]:
    return {
        **share_payload(),
        "resource_type": "conversation",
        "resource_id": "conv-1",
        "granted_member_id": None,
        "granted_tag": TAG,
        "visible_from": CUTOFF,
        "url": "https://example.test/v1/conversations/conv-1/items",
        **overrides,
    }


def test_share_create_tag_grant_sends_visible_from(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/shares", json_body=tag_share_payload())

    created = Shares(fake_api.client()).create(
        resource_type=ShareResourceType.CONVERSATION,
        resource_id="conv-1",
        granted_tag=TAG,
        visible_from=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert fake_api.last_request.json() == {
        "resource_type": "conversation",
        "resource_id": "conv-1",
        "granted_tag": TAG,
        "visible_from": "2026-01-01T00:00:00Z",
    }
    assert created.granted_tag == TAG
    assert created.granted_member_id is None
    assert created.visible_from == datetime(2026, 1, 1, tzinfo=UTC)
    # Shares are ambient: the url is the plain resource URL.
    assert created.url is not None and "share_id" not in created.url


def test_share_create_member_and_tag_grant_on_an_issue(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        "/v1/shares",
        json_body=tag_share_payload(
            resource_type="issue",
            resource_id="issue-1",
            granted_member_id=MEMBER_ID,
            visible_from=None,
        ),
    )

    created = Shares(fake_api.client()).create(
        resource_type="issue",
        resource_id="issue-1",
        granted_member_id=MEMBER_ID,
        granted_tag=TAG,
    )

    assert fake_api.last_request.json() == {
        "resource_type": "issue",
        "resource_id": "issue-1",
        "granted_member_id": MEMBER_ID,
        "granted_tag": TAG,
    }
    assert created.resource_type is ShareResourceType.ISSUE


def test_share_create_duplicate_tag_share_raises_conflict(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/shares",
        status=409,
        json_body={"detail": "An identical live share already exists"},
    )

    with pytest.raises(ConflictError, match="identical live share"):
        Shares(fake_api.client()).create(
            resource_type="file", resource_id="file-1", granted_tag=TAG
        )


def test_share_read_has_no_mode_field():
    share = ResourceShare.model_validate(share_payload())

    # A share admits; the caller's scopes decide what they may do.
    assert "mode" not in ResourceShare.model_fields
    assert share.granted_tag is None
    assert share.visible_from is None


def test_shares_list_sends_grantee_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/shares",
        json_body=paginated(
            [ResourceShare.model_validate(tag_share_payload())]
        ),
    )

    listed = (
        Shares(fake_api.client())
        .list(
            resource_type=ShareResourceType.CONVERSATION,
            granted_member_id=MEMBER_ID,
            granted_tag=TAG,
            granted_to_me=True,
        )
        .page()
    )

    params = fake_api.last_request.params
    assert params["resource_type"] == "conversation"
    assert params["granted_member_id"] == MEMBER_ID
    assert params["granted_tag"] == TAG
    assert params["granted_to_me"] == "true"
    assert listed.records[0].granted_tag == TAG


def test_shares_update_none_clears_visible_from(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/shares/{SHARE_ID}",
        json_body=tag_share_payload(visible_from=None),
    )

    updated = Shares(fake_api.client()).update(SHARE_ID, visible_from=None)

    # An explicit None goes on the wire as null: that is what clears it.
    assert fake_api.last_request.json() == {"visible_from": None}
    assert updated.visible_from is None


def test_shares_update_sets_visible_from(fake_api: FakeAPI):
    fake_api.add(
        "PATCH", f"/v1/shares/{SHARE_ID}", json_body=tag_share_payload()
    )

    updated = Shares(fake_api.client()).update(
        SHARE_ID, visible_from=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert fake_api.last_request.json() == {
        "visible_from": "2026-01-01T00:00:00Z"
    }
    assert updated.visible_from == datetime(2026, 1, 1, tzinfo=UTC)


def test_share_update_request_is_visible_from_only():
    # The update body is `visible_from` only; mode no longer exists.
    assert set(ShareUpdateRequest.model_fields) == {"visible_from"}


def test_shares_update_by_a_non_grantor_is_not_found(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/shares/{SHARE_ID}",
        status=404,
        json_body={"detail": "Share not found"},
    )

    with pytest.raises(NotFoundError):
        Shares(fake_api.client()).update(SHARE_ID, visible_from=None)


def test_shares_update_rejected_by_the_api_raises_validation_error(
    fake_api: FakeAPI,
):
    fake_api.add(
        "PATCH",
        f"/v1/shares/{SHARE_ID}",
        status=422,
        json_body={
            "detail": "visible_from applies to conversation shares only"
        },
    )

    with pytest.raises(ValidationError):
        Shares(fake_api.client()).update(SHARE_ID, visible_from=None)


async def test_async_shares_update_and_list_filters(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/shares/{SHARE_ID}",
        json_body=tag_share_payload(visible_from=None),
    )
    fake_api.add(
        "GET",
        "/v1/shares",
        json_body=paginated(
            [ResourceShare.model_validate(tag_share_payload())]
        ),
    )
    shares = AsyncShares(fake_api.async_client())

    updated = await shares.update(SHARE_ID, visible_from=None)
    assert fake_api.last_request.json() == {"visible_from": None}
    assert updated.visible_from is None

    page = await shares.list(granted_tag=TAG).page()
    assert fake_api.last_request.params["granted_tag"] == TAG
    assert page.records[0].granted_tag == TAG


async def test_async_shares_create_tag_grant(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/shares", json_body=tag_share_payload())

    created = await AsyncShares(fake_api.async_client()).create(
        resource_type="conversation",
        resource_id="conv-1",
        granted_tag=TAG,
        visible_from=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert fake_api.last_request.json() == {
        "resource_type": "conversation",
        "resource_id": "conv-1",
        "granted_tag": TAG,
        "visible_from": "2026-01-01T00:00:00Z",
    }
    assert created.granted_tag == TAG
