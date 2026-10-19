"""Live CRUD walks against a real deployment.

The ``tests/rest`` suites pin what the SDK *sends*; these pin that a deployed
API *answers* it, and they are what ``introspection-cloud``'s backend coverage
run drives. Each walk creates what it reads and deletes it again. The walks
mirror ``tests/live_api_test.rs`` in ``introspection-rust-sdk``. See
``conftest.py`` for how to run them.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import TypeVar

import pytest

from introspection_sdk import (
    AuthenticationError,
    IntrospectionClient,
    NotFoundError,
    ValidationError,
)
from introspection_sdk.schemas.automations import AutomationTriggerType
from introspection_sdk.schemas.events import IntrospectionEventName
from introspection_sdk.schemas.metrics import MetricQueryRequest, MetricSpec
from introspection_sdk.schemas.shares import ShareResourceType
from introspection_sdk.schemas.tags import (
    AccessTagCreate,
    AnnotationTagCreate,
    TagKind,
    TagUpdate,
)
from tests.live._support import setting, unique, uuid7

pytestmark = pytest.mark.live

T = TypeVar("T")

#: Upper bound on the rows a walk reads back while looking for what it made.
ROWS = 500


def collect(rows: Iterable[T]) -> list[T]:
    return list(islice(rows, ROWS))


def test_files_crud_walk(api_client: IntrospectionClient) -> None:
    files = api_client.files
    name = unique("file") + ".txt"
    created = files.create_text(
        name=name,
        content="hello from the python sdk",
        mime_type="text/plain",
        metadata={"suite": "live"},
    )
    file_id = str(created.id)
    try:
        assert files.get(file_id).name == name

        listed = collect(files.list(name=name, include_total=True))
        assert any(file.id == created.id for file in listed)

        renamed = unique("renamed") + ".txt"
        updated = files.update(
            file_id, name=renamed, metadata={"suite": "live-updated"}
        )
        assert updated.name == renamed

        assert files.download(file_id) == b"hello from the python sdk"

        version = files.versions.create(
            file_id,
            file=b"second version",
            name=renamed,
            content_type="text/plain",
        )
        versions = collect(files.versions.list(file_id))
        assert any(v.id == version.id for v in versions)
        assert files.versions.get(file_id, str(version.id)).id == version.id

        files.delete(file_id)
        with pytest.raises(NotFoundError) as excinfo:
            files.get(file_id)
        assert excinfo.value.status_code == 404
    finally:
        with contextlib.suppress(NotFoundError):
            files.delete(file_id)


def test_upload_and_shares_crud_walk(
    api_client: IntrospectionClient, member_client: IntrospectionClient
) -> None:
    files = api_client.files
    uploaded = files.upload(
        file=b"shared bytes",
        name=unique("shared") + ".bin",
        content_type="application/octet-stream",
    )
    file_id = str(uploaded.id)
    shares = api_client.shares
    try:
        share = shares.create(
            resource_type=ShareResourceType.FILE,
            resource_id=file_id,
            granted_tag=unique("audience"),
        )
        share_id = str(share.id)
        try:
            assert shares.get(share_id).id == share.id
            listed = collect(
                shares.list(
                    resource_type=ShareResourceType.FILE,
                    resource_id=file_id,
                )
            )
            assert any(s.id == share.id for s in listed)

            # `visible_from` windows a conversation's history; a file share
            # refuses it.
            with pytest.raises(ValidationError) as invalid:
                shares.update(
                    share_id, visible_from=datetime(2026, 1, 1, tzinfo=UTC)
                )
            assert invalid.value.status_code == 422

            # No API key capability carries `shares:delete`, so the member
            # removes it.
            member_client.shares.delete(share_id)
            with pytest.raises(NotFoundError) as excinfo:
                shares.get(share_id)
            assert excinfo.value.status_code == 404
        finally:
            with contextlib.suppress(NotFoundError):
                member_client.shares.delete(share_id)
    finally:
        with contextlib.suppress(NotFoundError):
            files.delete(file_id)


def test_tags_crud_walk(member_client: IntrospectionClient) -> None:
    tags = member_client.tags
    access = unique("access")
    annotation = unique("label")

    tags.create(AccessTagCreate(name=access))
    created = tags.create(
        AnnotationTagCreate(name=annotation, color="#f97316")
    )
    try:
        assert tags.get(TagKind.ACCESS, access).name == access
        assert tags.get(TagKind.ANNOTATION, created.name).name == created.name
        listed = collect(tags.list(TagKind.ANNOTATION))
        assert any(tag.name == created.name for tag in listed)

        updated = tags.update(
            TagKind.ANNOTATION,
            created.name,
            TagUpdate(color="#22c55e", description="recolored"),
        )
        assert updated.description == "recolored"

        tags.delete(TagKind.ANNOTATION, created.name)
        tags.delete(TagKind.ACCESS, access)
        with pytest.raises(NotFoundError) as excinfo:
            tags.get(TagKind.ANNOTATION, created.name)
        assert excinfo.value.status_code == 404
    finally:
        with contextlib.suppress(NotFoundError):
            tags.delete(TagKind.ANNOTATION, created.name)
        with contextlib.suppress(NotFoundError):
            tags.delete(TagKind.ACCESS, access)


def test_automations_crud_walk(member_client: IntrospectionClient) -> None:
    # An automation dispatches into a runtime group, so it needs a runtime the
    # seed does not create.
    runtime_group_id = setting("INTROSPECTION_RUNTIME_GROUP_ID")
    automations = member_client.automations
    created = automations.create(
        name=unique("automation"),
        trigger_type=AutomationTriggerType.MANUAL,
        description="created by the python sdk live suite",
        prompt="Reply with exactly: hi",
        runtime_group_id=runtime_group_id,
        enabled=False,
    )
    try:
        assert automations.get(created.id).id == created.id
        listed = collect(automations.list())
        assert any(a.id == created.id for a in listed)
        updated = automations.update(created.id, description="updated")
        assert updated.description == "updated"

        automations.delete(created.id)
        # `get` reads soft-deleted automations too (unlike the Rust walk's
        # 404), so a deleted one answers with `deleted_at` and leaves the list.
        assert automations.get(created.id).deleted_at is not None
        listed = collect(automations.list())
        assert all(a.id != created.id for a in listed)
    finally:
        with contextlib.suppress(NotFoundError):
            automations.delete(created.id)


def test_control_plane_reads(api_client: IntrospectionClient) -> None:
    project = setting("INTROSPECTION_PROJECT")
    collect(api_client.runtimes.list(project=project))
    collect(api_client.recipes.list(project=project))
    collect(api_client.experiments.list(project=project))
    collect(api_client.connectors.list())
    with pytest.raises(NotFoundError) as excinfo:
        api_client.recipes.get(uuid7())
    assert excinfo.value.status_code == 404


def test_telemetry_reads(api_client: IntrospectionClient) -> None:
    api_client.conversations.list().page()
    api_client.events.list(IntrospectionEventName.ANNOTATION).page()


def test_metrics_query(api_client: IntrospectionClient) -> None:
    now = datetime.now(UTC)
    result = api_client.metrics.query(
        MetricQueryRequest(
            view="conversations",
            metrics=[MetricSpec(aggregation="count")],
            from_timestamp=now - timedelta(days=1),
            to_timestamp=now,
        )
    )
    assert result.meta is not None


def test_members_reads_with_session(
    session_client: IntrospectionClient,
) -> None:
    members = collect(session_client.members.list())
    assert members, "the seeded org has members"
    assert session_client.members.get(members[0].id).id == members[0].id


def test_rejected_credentials_are_typed(
    make_client: Callable[..., IntrospectionClient],
) -> None:
    setting("INTROSPECTION_DP_URL")
    bogus = make_client("intro_dev_not_a_real_key")
    with pytest.raises(AuthenticationError) as excinfo:
        bogus.files.get(str(uuid7()))
    assert excinfo.value.status_code == 401
