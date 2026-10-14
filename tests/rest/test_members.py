"""Contract tests for ``client.members`` and member tags + metadata."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk import IntrospectionClient
from introspection_sdk._errors import IntrospectionAPIError, ValidationError
from introspection_sdk.resources.members import AsyncMembers, Members
from introspection_sdk.schemas.members import (
    BusinessMemberCreate,
    CustomerMemberCreate,
    MemberType,
)

from .conftest import (
    MEMBER_ID,
    PROJECT_ID,
    FakeAPI,
    member_payload,
    paginated,
)

MEMBER_PATH = f"/v1/members/{MEMBER_ID}"
MEMBER_UUID = UUID(MEMBER_ID)


def test_client_exposes_members():
    client = IntrospectionClient(token="t", base_api_url="https://api.test")
    try:
        assert isinstance(client.members, Members)
    finally:
        client.shutdown()


def test_list_parses_tags_and_metadata(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/members",
        json_body=paginated(
            [
                member_payload(
                    tags=["team:acme"], metadata={"plan": "enterprise"}
                )
            ],
            next="cursor-2",
        ),
    )
    page = Members(fake_api.client()).list().page()

    assert page.next == "cursor-2"
    member = page.records[0]
    assert member.tags == ["team:acme"]
    assert member.metadata == {"plan": "enterprise"}
    assert member.member_type is MemberType.BUSINESS


def test_member_without_metadata_reads_as_empty_map(fake_api: FakeAPI):
    # A server that predates member metadata omits the field entirely.
    body = member_payload().model_dump(mode="json")
    del body["metadata"], body["tags"]
    fake_api.add("GET", MEMBER_PATH, json_body=body)

    member = Members(fake_api.client()).get(MEMBER_UUID)

    assert member.metadata == {}
    assert member.tags == []


def test_list_sends_metadata_as_repeated_pairs(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/members", json_body=paginated([]))
    Members(fake_api.client()).list(
        metadata={"plan": "enterprise", "ref": "crm:42"},
        tag="customer:acme",
        member_type=MemberType.CUSTOMER,
        project=PROJECT_ID,
        limit=10,
    ).page()

    params = fake_api.last_request.params
    assert params.get_list("metadata") == ["plan:enterprise", "ref:crm:42"]
    assert params["tag"] == "customer:acme"
    assert params["member_type"] == "customer"
    assert params["project"] == PROJECT_ID
    assert params["limit"] == "10"


def test_list_omits_unset_and_empty_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/members", json_body=paginated([]))
    Members(fake_api.client()).list(metadata={}).page()

    params = fake_api.last_request.params
    for name in ("metadata", "tag", "member_type", "project"):
        assert name not in params


def test_list_surfaces_a_rejected_filter(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/members",
        status=422,
        json_body={"detail": "metadata filter keys must be distinct"},
    )
    with pytest.raises(ValidationError) as exc:
        Members(fake_api.client()).list(metadata={"user.tier": "gold"}).page()
    assert exc.value.status_code == 422


def test_get_passes_project(fake_api: FakeAPI):
    fake_api.add("GET", MEMBER_PATH, json_body=member_payload())
    member = Members(fake_api.client()).get(MEMBER_UUID, project=PROJECT_ID)

    assert member.id == MEMBER_UUID
    assert fake_api.last_request.params["project"] == PROJECT_ID


def test_create_sends_tags_and_metadata(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/members",
        status=201,
        json_body=member_payload(
            tags=["team:acme"], metadata={"plan": "enterprise"}
        ),
    )
    member = Members(fake_api.client()).create(
        BusinessMemberCreate(
            email="ada@example.com",
            name="Ada Lovelace",
            role="admin",
            tags=["team:acme"],
            metadata={"plan": "enterprise"},
        )
    )

    assert fake_api.last_request.json() == {
        "member_type": "business",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "role": "admin",
        "tags": ["team:acme"],
        "metadata": {"plan": "enterprise"},
    }
    assert member.metadata == {"plan": "enterprise"}


def test_create_omits_unset_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/members", status=201, json_body=member_payload())
    Members(fake_api.client()).create(
        BusinessMemberCreate(email="ada@example.com", name="Ada Lovelace")
    )

    assert fake_api.last_request.json() == {
        "member_type": "business",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
    }


def test_create_with_tags_without_manage_scope_is_forbidden(
    fake_api: FakeAPI,
):
    fake_api.add(
        "POST",
        "/v1/members",
        status=403,
        json_body={"detail": "Setting member tags requires members:manage."},
    )
    with pytest.raises(IntrospectionAPIError) as exc:
        Members(fake_api.client()).create(
            BusinessMemberCreate(
                email="ada@example.com",
                name="Ada Lovelace",
                tags=["team:acme"],
            )
        )
    assert exc.value.status_code == 403


def test_create_customer_member_sends_its_variant(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/members",
        status=201,
        json_body=member_payload(
            member_type=MemberType.CUSTOMER,
            email=None,
            name=None,
            external_user_id="user:42",
            policy_attributes={"level": 3},
        ),
    )

    member = Members(fake_api.client()).create(
        CustomerMemberCreate(
            external_user_id="user:42",
            metadata={"plan": "pro"},
            policy_attributes={"level": 3},
        )
    )

    assert fake_api.last_request.json() == {
        "member_type": "customer",
        "external_user_id": "user:42",
        "metadata": {"plan": "pro"},
        "policy_attributes": {"level": 3},
    }
    assert member.member_type is MemberType.CUSTOMER
    assert member.external_user_id == "user:42"


def test_create_dict_without_member_type_is_a_business_member(
    fake_api: FakeAPI,
):
    fake_api.add("POST", "/v1/members", status=201, json_body=member_payload())

    Members(fake_api.client()).create(
        {"email": "ada@example.com", "name": "Ada Lovelace", "role": "admin"}
    )

    assert fake_api.last_request.json() == {
        "member_type": "business",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "role": "admin",
    }


def test_create_dict_with_customer_member_type(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/members", status=201, json_body=member_payload())

    Members(fake_api.client()).create(
        {"member_type": "customer", "external_user_id": "anon:7"}
    )

    assert fake_api.last_request.json() == {
        "member_type": "customer",
        "external_user_id": "anon:7",
    }


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"member_type": "customer"}, id="customer-no-user-id"),
        pytest.param({"name": "Ada Lovelace"}, id="business-no-email"),
        pytest.param(
            {
                "member_type": "customer",
                "external_user_id": "user:1",
                "role": "admin",
            },
            id="customer-with-role",
        ),
        pytest.param(
            {"member_type": "agent", "name": "bot"}, id="unknown-member-type"
        ),
    ],
)
def test_create_rejects_an_invalid_body_before_sending(
    fake_api: FakeAPI, body: dict[str, object]
):
    with pytest.raises(PydanticValidationError):
        Members(fake_api.client()).create(body)
    assert fake_api.requests == []


def test_create_models_require_their_identifying_fields():
    with pytest.raises(PydanticValidationError):
        CustomerMemberCreate.model_validate({})
    with pytest.raises(PydanticValidationError):
        BusinessMemberCreate.model_validate({"name": "Ada Lovelace"})


def test_update_replaces_metadata(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        MEMBER_PATH,
        json_body=member_payload(metadata={"plan": "pro"}),
    )
    member = Members(fake_api.client()).update(
        MEMBER_UUID, metadata={"plan": "pro"}
    )

    assert fake_api.last_request.json() == {"metadata": {"plan": "pro"}}
    assert member.metadata == {"plan": "pro"}


def test_update_with_empty_maps_clears(fake_api: FakeAPI):
    fake_api.add("PATCH", MEMBER_PATH, json_body=member_payload())
    Members(fake_api.client()).update(MEMBER_UUID, tags=[], metadata={})

    assert fake_api.last_request.json() == {"tags": [], "metadata": {}}


def test_update_omits_untouched_fields(fake_api: FakeAPI):
    fake_api.add("PATCH", MEMBER_PATH, json_body=member_payload())
    Members(fake_api.client()).update(MEMBER_UUID, name="Ada King")

    assert fake_api.last_request.json() == {"name": "Ada King"}


def test_update_surfaces_invalid_metadata(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        MEMBER_PATH,
        status=422,
        json_body={"detail": "a metadata key must not contain '.'"},
    )
    with pytest.raises(ValidationError):
        Members(fake_api.client()).update(
            MEMBER_UUID, metadata={"user.tier": "gold"}
        )


POLICY_ATTRIBUTES = {
    "level": 7,
    "company": {"__entity": {"type": "Company", "id": "acme"}},
}


def test_read_parses_policy_attributes(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        MEMBER_PATH,
        json_body=member_payload(policy_attributes=POLICY_ATTRIBUTES),
    )

    member = Members(fake_api.client()).get(MEMBER_UUID)

    assert member.policy_attributes == POLICY_ATTRIBUTES


def test_read_without_policy_attributes_is_none(fake_api: FakeAPI):
    fake_api.add("GET", MEMBER_PATH, json_body=member_payload())

    assert (
        Members(fake_api.client()).get(MEMBER_UUID).policy_attributes is None
    )


def test_create_sends_policy_attributes(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/members",
        status=201,
        json_body=member_payload(policy_attributes=POLICY_ATTRIBUTES),
    )

    member = Members(fake_api.client()).create(
        BusinessMemberCreate(
            email="ada@example.com",
            name="Ada Lovelace",
            policy_attributes=POLICY_ATTRIBUTES,
        )
    )

    assert fake_api.last_request.json() == {
        "member_type": "business",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "policy_attributes": POLICY_ATTRIBUTES,
    }
    assert member.policy_attributes == POLICY_ATTRIBUTES


def test_update_replaces_policy_attributes(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        MEMBER_PATH,
        json_body=member_payload(policy_attributes=POLICY_ATTRIBUTES),
    )

    member = Members(fake_api.client()).update(
        MEMBER_UUID, policy_attributes=POLICY_ATTRIBUTES
    )

    assert fake_api.last_request.json() == {
        "policy_attributes": POLICY_ATTRIBUTES
    }
    assert member.policy_attributes == POLICY_ATTRIBUTES


def test_update_policy_attributes_without_manage_scope_is_forbidden(
    fake_api: FakeAPI,
):
    fake_api.add(
        "PATCH",
        MEMBER_PATH,
        status=403,
        json_body={"detail": "Requires members:manage."},
    )
    with pytest.raises(IntrospectionAPIError) as exc:
        Members(fake_api.client()).update(
            MEMBER_UUID, policy_attributes={"level": 9}
        )
    assert exc.value.status_code == 403


async def test_async_create_and_update_send_policy_attributes(
    fake_api: FakeAPI,
):
    fake_api.add("POST", "/v1/members", status=201, json_body=member_payload())
    fake_api.add("PATCH", MEMBER_PATH, json_body=member_payload())
    members = AsyncMembers(fake_api.async_client())

    await members.create(
        CustomerMemberCreate(
            external_user_id="user:42", policy_attributes={"level": 3}
        )
    )
    assert fake_api.last_request.json()["policy_attributes"] == {"level": 3}

    await members.update(MEMBER_UUID, policy_attributes=POLICY_ATTRIBUTES)
    assert fake_api.last_request.json() == {
        "policy_attributes": POLICY_ATTRIBUTES
    }


async def test_async_list_sends_metadata_and_tag(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/members",
        json_body=paginated([member_payload(metadata={"plan": "pro"})]),
    )
    page = await AsyncMembers(fake_api.async_client()).list(
        metadata={"plan": "pro"}, tag="team:acme"
    )

    assert page.records[0].metadata == {"plan": "pro"}
    params = fake_api.last_request.params
    assert params.get_list("metadata") == ["plan:pro"]
    assert params["tag"] == "team:acme"


async def test_async_get_create_and_update(fake_api: FakeAPI):
    fake_api.add("GET", MEMBER_PATH, json_body=member_payload())
    fake_api.add(
        "POST",
        "/v1/members",
        status=201,
        json_body=member_payload(metadata={"plan": "pro"}),
    )
    fake_api.add("PATCH", MEMBER_PATH, json_body=member_payload())
    members = AsyncMembers(fake_api.async_client())

    assert (await members.get(MEMBER_UUID)).id == MEMBER_UUID

    created = await members.create(
        {
            "email": "ada@example.com",
            "name": "Ada Lovelace",
            "metadata": {"plan": "pro"},
        }
    )
    assert created.metadata == {"plan": "pro"}
    assert fake_api.last_request.json()["metadata"] == {"plan": "pro"}

    await members.update(MEMBER_UUID, metadata={})
    assert fake_api.last_request.json() == {"metadata": {}}
