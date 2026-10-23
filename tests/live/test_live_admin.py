"""Live walks of the project administration and eval resources.

These pin that a deployed API answers what ``tests/rest/test_project_admin.py``
and ``tests/rest/test_images.py`` pin the SDK sends. They mirror the walks of
the same names in ``introspection-rust-sdk``'s ``tests/live_api_test.rs``.
Each walk creates what it reads and deletes it again. Marked ``live`` and
deselected by default; run with::

    INTROSPECTION_LIVE=1 uv run pytest tests/live -m live -p no:cacheprovider

Settings, each skipping the walks that need it when unset:

- ``INTROSPECTION_BASE_API_URL``: the Control Plane.
- ``INTROSPECTION_CP_SESSION``: an owner's Control Plane session cookie. The
  administration routes need an org credential, which no project API key or
  service account is; a bearer beside the cookie is refused, so it is sent
  alone.
- ``INTROSPECTION_PROJECT``: the seeded project's slug, which a member session
  must name on project-scoped routes.
- ``INTROSPECTION_DP_URL`` and ``INTROSPECTION_MEMBER_TOKEN`` (an owner's Data
  Plane token): ``images`` and ``tasks.commands``, which need ``images:*`` /
  ``tasks:exec``.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar
from uuid import UUID

import pytest

from introspection_sdk import IntrospectionClient
from introspection_sdk._errors import (
    ConflictError,
    IntrospectionAPIError,
    NotFoundError,
    ValidationError,
)
from introspection_sdk.schemas.api_keys import ApiKeyStatus
from introspection_sdk.schemas.applications import ApplicationType
from introspection_sdk.schemas.images import ImageKind, MirrorImageSource
from introspection_sdk.schemas.integrations import (
    IntegrationStatus,
    IntegrationType,
)
from introspection_sdk.schemas.lanes import Environment
from introspection_sdk.schemas.task_commands import ExecCommand

pytestmark = pytest.mark.live

T = TypeVar("T")

#: Upper bound on the rows a walk reads back while looking for what it made.
ROWS = 500


def collect(rows: Iterable[T]) -> list[T]:
    return list(islice(rows, ROWS))


def uuid7() -> UUID:
    """A UUIDv7; ``uuid.uuid7`` is 3.14+ and this package supports 3.11."""
    value = ((int(time.time() * 1000) & ((1 << 48) - 1)) << 80) | (
        secrets.randbits(80)
    )
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return UUID(int=value)


def unique(prefix: str) -> str:
    """A name no other run shares, so concurrent runs never collide and a
    leftover from a crashed run is recognisable."""
    return f"sdk-{prefix}-{uuid7().hex}"


def env_name() -> str:
    """An environment-variable-shaped unique name."""
    return f"SDK_{uuid7().hex}".upper()


def setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


@pytest.fixture(autouse=True)
def _require_live() -> None:
    if os.environ.get("INTROSPECTION_LIVE") != "1":
        pytest.skip("INTROSPECTION_LIVE is not 1")


@pytest.fixture
def owner_session() -> Iterator[IntrospectionClient]:
    """An owner's Control Plane session cookie alone."""
    client = IntrospectionClient(
        cp_session=setting("INTROSPECTION_CP_SESSION"),
        base_api_url=setting("INTROSPECTION_BASE_API_URL"),
    )
    yield client
    client.shutdown()


@pytest.fixture
def owner_dp() -> Iterator[IntrospectionClient]:
    """An owner's Data Plane token."""
    client = IntrospectionClient(
        token=setting("INTROSPECTION_MEMBER_TOKEN"),
        base_api_url=setting("INTROSPECTION_BASE_API_URL"),
        dp_url=setting("INTROSPECTION_DP_URL"),
    )
    yield client
    client.shutdown()


@pytest.fixture
def project() -> str:
    return setting("INTROSPECTION_PROJECT")


def test_oidc_me_with_session(owner_session: IntrospectionClient) -> None:
    me = owner_session.oidc.me()
    assert me.authenticated
    assert me.member_id is not None, "a member session names its member"
    assert me.org_id is not None


def test_api_keys_crud_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    keys = owner_session.api_keys
    created = keys.create(
        project=project,
        name=unique("key"),
        environment=Environment.DEVELOPMENT,
    )
    try:
        assert created.api_key is not None, "the plaintext rides the create"
        assert keys.acknowledge(created.id, project=project).acknowledged
        with pytest.raises(NotFoundError):
            keys.acknowledge(created.id, project=project)

        assert any(k.id == created.id for k in keys.list(project=project))
        renamed = unique("key-renamed")
        updated = keys.update(created.id, project=project, name=renamed)
        assert updated.name == renamed

        keys.delete(created.id, project=project)
        assert not any(
            k.id == created.id and k.status is ApiKeyStatus.ACTIVE
            for k in keys.list(project=project)
        )
    finally:
        with contextlib.suppress(NotFoundError):
            keys.delete(created.id, project=project)


def test_applications_crud_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    applications = owner_session.applications
    # Every plan may create a service account; browser and federated types
    # are plan-gated.
    created = applications.create(
        name=unique("app"),
        application_type=ApplicationType.SERVICE_ACCOUNT,
        project=project,
    )
    app_id = created.id
    try:
        applications.get(app_id, project=project)
        listed = collect(applications.list(project=project))
        assert any(a.id == app_id for a in listed)
        renamed = unique("app-renamed")
        assert (
            applications.update(app_id, project=project, name=renamed).name
            == renamed
        )

        secret = applications.secrets.create(app_id, name=unique("secret"))
        assert secret.secret is not None, "the plaintext rides the create"
        secrets_listed = collect(applications.secrets.list(app_id))
        assert any(s.id == secret.id for s in secrets_listed)
        applications.secrets.delete(app_id, secret.id)

        key = applications.keys.create(app_id)
        assert any(k.id == key.id for k in applications.keys.list(app_id))
        applications.keys.delete(app_id, key.id)

        assert collect(applications.idps.list(app_id)) == []
        # A service account federates no end users, so the attach is
        # refused; reaching that refusal is what pins the route and body.
        with pytest.raises(IntrospectionAPIError) as refused:
            applications.idps.create(app_id, issuer="https://idp.example.com")
        assert refused.value.status_code in (400, 403)

        applications.delete(app_id, project=project)
        with pytest.raises(NotFoundError):
            applications.get(app_id, project=project)
    finally:
        with contextlib.suppress(NotFoundError):
            applications.delete(app_id, project=project)


def test_credentials_crud_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    credentials = owner_session.credentials
    name = env_name()
    created = credentials.create(
        name=name, secret="sk-live-suite", project=project
    )
    try:
        assert created.has_secret
        assert credentials.get(created.id, project=project).name == name
        listed = collect(credentials.list(project=project))
        assert any(c.id == created.id for c in listed)
        credentials.update(created.id, project=project, secret="sk-rotated")

        credentials.delete(created.id, project=project)
        with pytest.raises(NotFoundError):
            credentials.get(created.id, project=project)
    finally:
        with contextlib.suppress(NotFoundError):
            credentials.delete(created.id, project=project)


def test_variables_crud_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    variables = owner_session.variables
    created = variables.create(name=env_name(), value="one", project=project)
    try:
        assert created.value == "one"
        updated = variables.update(created.id, project=project, value="two")
        assert updated.value == "two"
        listed = collect(variables.list(project=project))
        assert any(v.id == created.id for v in listed)

        variables.delete(created.id, project=project)
        listed = collect(variables.list(project=project))
        assert all(v.id != created.id for v in listed)
    finally:
        with contextlib.suppress(NotFoundError):
            variables.delete(created.id, project=project)


def test_integrations_crud_walk(owner_session: IntrospectionClient) -> None:
    integrations = owner_session.integrations
    # One live integration per type per org: a create returns the pending
    # one if it exists, and 409s on an active one.
    try:
        created = integrations.create(
            integration_type=IntegrationType.CUSTOM, name=unique("integration")
        )
    except ConflictError:
        pytest.skip("the org already has an active custom integration")
    try:
        assert created.status is IntegrationStatus.PENDING
        integrations.get(created.id)
        assert any(i.id == created.id for i in collect(integrations.list()))
        renamed = unique("integration-renamed")
        assert integrations.update(created.id, name=renamed).name == renamed

        integrations.delete(created.id)
        with pytest.raises(NotFoundError):
            integrations.get(created.id)
    finally:
        with contextlib.suppress(NotFoundError):
            integrations.delete(created.id)


def test_judges_read_and_update_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    judges = owner_session.judges
    listed = collect(judges.list(project=project))
    with pytest.raises(NotFoundError):
        judges.get(uuid7(), project=project)
    # Judges are published with a Recipe, so a project without one has none
    # to read; the update writes back the judge's own values.
    if not listed:
        pytest.skip("the project has no judges")
    fetched = judges.get(listed[0].id, project=project)
    updated = judges.update(
        fetched.id,
        project=project,
        enabled=fetched.enabled,
        sample_rate=fetched.sample_rate,
    )
    assert updated.enabled == fetched.enabled


def test_projects_read_walk(
    owner_session: IntrospectionClient, project: str
) -> None:
    projects = owner_session.projects
    seeded = projects.get(project)
    assert seeded.slug == project
    assert any(p.id == seeded.id for p in collect(projects.list()))


def test_images_crud_walk(owner_dp: IntrospectionClient) -> None:
    images = owner_dp.images
    collect(images.list())
    with pytest.raises(NotFoundError):
        images.get(uuid7())

    # A digest no registry serves: the create only records intent, and the
    # build it sends fails on the row without touching anything else.
    source = MirrorImageSource(
        reference=f"registry.invalid/sdk/live@sha256:{'0' * 64}"
    )
    try:
        created = images.create(name=unique("image"), source=source)
    except ValidationError as error:
        if error.status_code != 422:
            raise
        pytest.skip(f"evals are not enabled on this plane ({error})")
    try:
        assert created.kind is ImageKind.SERVICE
        images.get(created.id)
        images.delete(created.id)
        with pytest.raises(NotFoundError):
            images.get(created.id)
    finally:
        with contextlib.suppress(NotFoundError):
            images.delete(created.id)


def test_task_commands_reads(owner_dp: IntrospectionClient) -> None:
    commands = owner_dp.tasks.commands
    task_id = str(uuid7())

    # A command needs an eval task with a live sandbox, which the seed does
    # not run; these pin the routes, the credential and the error shapes.
    assert collect(commands.list(task_id)) == []
    with pytest.raises(NotFoundError):
        commands.get(task_id, uuid7())
    with pytest.raises(IntrospectionAPIError) as refused:
        commands.create(task_id, ExecCommand(command=["true"]))
    # 404 for the missing task, or 422 on a plane without evals.
    assert refused.value.status_code in (404, 422)
