"""The SDK end-to-end walk: one ordered scenario from a clean project to a
graded eval, every step an SDK call, replaying this SDK's recording
(introspection-cloud ``docs/design/sdk-end-to-end-walk.md``).

The steps, their names and their order are the design doc's, the same in
every SDK; ``tests/recordings/walk/recording.har`` is this SDK's own. Replay (the default
``uv run pytest``) needs no stack, no keys and no network. A live run needs
a signed-in ``introspection login`` (or ``INTROSPECTION_CP_SESSION``)::

    VCR_MODE=record uv run pytest tests/walk       # re-record the HAR
    VCR_MODE=passthrough uv run pytest tests/walk  # live, records nothing

Every call is an SDK method; the walk has no raw HTTP helper, so a route the
SDK has no method for gets one before the walk calls it.
"""

from __future__ import annotations

import io
import json
import re
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from dirty_equals import AnyThing, IsInt, IsPositiveInt, IsUUID
from vcr.cassette import Cassette

from introspection_sdk import (
    ConflictError,
    IntrospectionAPIError,
    IntrospectionClient,
    NotFoundError,
    ValidationError,
)
from introspection_sdk.auth import (
    DEVICE_FLOW_CLIENT_ID,
    DeviceTokenStatus,
    development_credential,
    oidc_logout,
    poll_device_token,
    refresh_access_token,
    request_device_code,
    revoke_session,
    service_account_token,
)
from introspection_sdk.runner import Runner
from introspection_sdk.schemas.applications import Application
from introspection_sdk.schemas.connectors import Connector
from introspection_sdk.schemas.endpoints import Endpoint
from introspection_sdk.schemas.events import IntrospectionEventName
from introspection_sdk.schemas.experiments import Experiment
from introspection_sdk.schemas.files import File
from introspection_sdk.schemas.judges import Judge
from introspection_sdk.schemas.members import CustomerMemberCreate, MemberType
from introspection_sdk.schemas.projects import Project
from introspection_sdk.schemas.recipes import Recipe
from introspection_sdk.schemas.repositories import Repository
from introspection_sdk.schemas.runtimes import Runtime, RuntimeInclude
from introspection_sdk.schemas.tags import AccessTagCreate, TagKind, TagUpdate
from introspection_sdk.schemas.tasks import Task

from .conftest import HAR
from .settings import (
    APPLICATION_SCOPES,
    BOOTSTRAP_FILE,
    WALK,
    Mode,
    WalkSettings,
    prompt,
    second_turn,
    walk_settings,
)
from .stable import plain, stable
from .support import (
    QuietTransport,
    WalkReport,
    follow_authorization,
    prepare_recipe,
    push_recipe,
    settled,
    span_event_id,
    walk_project_born,
)
from .teardown import remove_walk_resources


def snapshot(_value: Any = None) -> Any:  # TEMPORARY: record run only
    return AnyThing


IDLE = ("idle", "awaiting_user", "completed")
#: An id nothing has: the reads of what the walk cannot make answer 404.
NIL = UUID(int=0)


@dataclass
class World:
    """What the steps share, in order."""

    mode: Mode
    settings: WalkSettings
    report: WalkReport
    owner: IntrospectionClient
    recipe_dir: Path | None = None
    sa: IntrospectionClient = field(init=False)
    sa_quiet: IntrospectionClient = field(init=False)
    member: IntrospectionClient = field(init=False)
    member_token: str = ""
    login_project: Project = field(init=False)
    project: Project = field(init=False)
    original_description: str | None = None
    application: Application = field(init=False)
    repository: Repository = field(init=False)
    recipe: Recipe = field(init=False)
    pinned_recipe: Recipe = field(init=False)
    connector: Connector = field(init=False)
    runtime: Runtime = field(init=False)
    runtime_v2: Runtime = field(init=False)
    endpoint: Endpoint = field(init=False)
    runner: Runner = field(init=False)
    input_file: File = field(init=False)
    task: Task = field(init=False)
    conversation_id: str = ""
    output_file: File = field(init=False)
    eval_task: Task = field(init=False)
    judge: Judge = field(init=False)
    experiment: Experiment = field(init=False)

    @property
    def group_id(self) -> str:
        return str(self.runtime.runtime_group_id)

    def quiet(self, **kwargs: Any) -> IntrospectionClient:
        """A client on the unrecorded transport, for polls (design doc §5)."""
        return IntrospectionClient(transport=QuietTransport(), **kwargs)


@pytest.fixture(scope="module")
def world(cassette: object, mode: Mode, report: WalkReport) -> Iterator[World]:
    settings = walk_settings(mode)
    recipe_dir = (
        prepare_recipe(
            settings.recipe_repository_url,
            settings.recipe_git_ref,
            settings.agent,
        )
        if mode != "replay"
        else None
    )
    owner = IntrospectionClient(
        cp_session=settings.cp_session, base_api_url=settings.base_api_url
    )
    yield World(mode, settings, report, owner, recipe_dir)
    if recipe_dir is not None:
        shutil.rmtree(recipe_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def step(request: pytest.FixtureRequest, report: WalkReport) -> None:
    """Each test is one step; after a failed one the rest skip, so one
    failure reads as one."""
    marker = request.node.get_closest_marker("walk_step")
    assert marker is not None, "every walk test names its step"
    n, name = marker.args
    request.node.walk_report = report
    request.node.walk_step = {"n": n, "name": name}
    if report.failed is not None:
        pytest.skip(f"after {report.failed} failed")


def expect_not_found(read: Any) -> None:
    with pytest.raises(NotFoundError):
        read()


def walk_step(n: int, name: str) -> pytest.MarkDecorator:
    return pytest.mark.walk_step(n, name)


@walk_step(0, "a project of its own, created empty on the login's deployment")
def test_00_clean_slate(world: World) -> None:
    # Every run starts in a project of its own, created here on the login's
    # deployment and deleted by the teardown. A record run writes both ids
    # beside the recording, which is all replay needs to send the same calls.
    w = world
    w.login_project = w.owner.projects.get(w.settings.bootstrap_project_id)
    # A run that crashed before its teardown left its project behind; one
    # still running is younger than the cutoff. Measured from this run's own
    # slug, so replay decides as the recording did.
    now = walk_project_born(w.settings.project_slug, WALK.project_slug_prefix)
    assert now is not None, "the walk's own slug carries its time"
    for other in w.owner.projects.list():
        born = walk_project_born(other.slug or "", WALK.project_slug_prefix)
        if born is not None and now - born > WALK.stale_after_seconds:
            w.owner.projects.delete(other.id)
    w.project = w.owner.projects.create(
        name="SDK end-to-end walk",
        slug=w.settings.project_slug,
        deployment_id=w.login_project.deployment_id,
    )
    if w.mode == "record":
        HAR.parent.mkdir(parents=True, exist_ok=True)
        (HAR.parent / BOOTSTRAP_FILE).write_text(
            json.dumps(
                {
                    "project_id": str(w.login_project.id),
                    "project_slug": w.settings.project_slug,
                }
            )
            + "\n"
        )
    # The owner's Data Plane token for the project: it carries `git:push`,
    # which no service account can, and the member-only Data Plane writes.
    minted = w.owner.tokens.create(project=w.project.id, expires_hours=24)
    assert minted.project_id == w.project.id
    w.member_token = minted.access_token.get_secret_value()
    w.member = IntrospectionClient(
        token=w.member_token,
        base_api_url=w.settings.base_api_url,
        dp_url=w.settings.dp_url,
    )


@walk_step(1, "project — read, list, update; a sibling created and deleted")
def test_01_project(world: World) -> None:
    w = world
    # The slug is new on every live run, so the snapshot leaves it out.
    assert stable(
        {**plain(w.project), "name": None, "slug": None, "description": None}
    ) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "deployment_id": "[uuid]",
            "name": None,
            "slug": None,
            "description": None,
            "settings": None,
            "created_by_member_id": "[uuid]",
        }
    )
    w.original_description = w.project.description
    assert w.owner.projects.get(str(w.project.id)).id == w.project.id
    assert any(p.id == w.project.id for p in w.owner.projects.list())

    projects = w.owner.projects
    updated = projects.update(
        w.project.id, description="The SDK end-to-end walk ran here"
    )
    assert updated.description == "The SDK end-to-end walk ran here"
    # A PATCH with only nulls is "no fields to update", so a project that
    # had no description gets an empty one back.
    restored = projects.update(
        w.project.id, description=w.original_description or ""
    )
    assert (restored.description or "") == (w.original_description or "")

    # A sibling is created and deleted while the walk's project is in use.
    sibling = projects.create(
        name=f"{w.project.name} (walk)",
        slug=f"{w.project.slug}{WALK.sibling_suffix}",
        deployment_id=w.project.deployment_id,
    )
    assert sibling.deployment_id == w.project.deployment_id
    assert stable({**plain(sibling), "name": None, "slug": None}) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "deployment_id": "[uuid]",
            "name": None,
            "slug": None,
            "description": None,
            "settings": None,
            "created_by_member_id": "[uuid]",
        }
    )
    projects.delete(sibling.id)
    expect_not_found(lambda: w.owner.projects.get(str(sibling.id)))


@walk_step(
    2,
    "application — a service account, its secret, and the token that names "
    "the Data Plane",
)
def test_02_application(world: World) -> None:
    w = world
    w.application = w.owner.applications.create(
        name=WALK.application_name,
        application_type="service_account",
        allowed_scopes=APPLICATION_SCOPES,
        project=w.project.id,
    )
    assert stable(w.application) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "name": "sdk-coverage-walk",
            "application_type": "service_account",
            "environment": "production",
            "redirect_uris": [],
            "allowed_origins": [],
            "allowed_scopes": [
                "projects:read",
                "repositories:read",
                "repositories:write",
                "repositories:delete",
                "recipes:read",
                "recipes:write",
                "runtimes:read",
                "runtimes:write",
                "experiments:read",
                "experiments:write",
                "tasks:read",
                "tasks:write",
                "tasks:delete",
                "tasks:eval",
                "tasks:exec",
                "files:read",
                "files:write",
                "files:delete",
                "conversations:read",
                "events:read",
                "metrics:read",
                "shares:read",
                "shares:write",
                "shares:delete",
                "connectors:read",
                "connectors:write",
                "connections:read",
                "connections:write",
                "connections:delete",
                "automations:read",
                "automations:write",
                "annotations:read",
                "approvals:read",
                "approvals:write",
                "images:read",
                "images:write",
                "api_keys:read",
                "api_keys:write",
                "api_keys:delete",
                "applications:read",
                "applications:write",
                "applications:delete",
                "credentials:read",
                "credentials:write",
                "credentials:delete",
                "endpoints:read",
                "endpoints:write",
                "endpoints:delete",
                "variables:read",
                "variables:write",
                "variables:delete",
                "judges:read",
                "judges:write",
                "telemetry:write",
            ],
            "client_id": "[redacted]",
            "agent_member_id": "[uuid]",
            "allowed_grants": ["client_credentials"],
            "last_used_at": None,
            "revoked_at": None,
            "created_by_member_id": "[uuid]",
        }
    )
    first = w.owner.applications.secrets.create(w.application.id, name="first")
    assert first.secret is not None, "the plaintext is returned once"

    minted = service_account_token(
        client_id=w.application.client_id,
        client_secret=first.secret.get_secret_value(),
        project=str(w.project.id),
        base_api_url=w.settings.base_api_url,
    )
    assert minted.dp_url, "the token response names the Data Plane"
    w.sa = IntrospectionClient(
        token=minted.access_token,
        base_api_url=w.settings.base_api_url,
        dp_url=minted.dp_url,
    )
    w.sa_quiet = w.quiet(
        token=minted.access_token,
        base_api_url=w.settings.base_api_url,
        dp_url=minted.dp_url,
    )

    apps = w.owner.applications
    assert any(
        a.id == w.application.id for a in apps.list(project=w.project.id)
    )
    read = apps.get(w.application.id, project=w.project.id)
    assert read.client_id == w.application.client_id
    renamed = apps.update(
        w.application.id,
        project=w.project.id,
        name=f"{WALK.application_name}-renamed",
    )
    assert renamed.name == f"{WALK.application_name}-renamed"

    # Rotate: a second secret, then the first revoked.
    second = apps.secrets.create(w.application.id, name="second")
    secrets = [
        {k: v for k, v in plain(s).items() if k != "secret"}
        for s in apps.secrets.list(w.application.id)
    ]
    assert stable(secrets) == snapshot(
        [
            {
                "id": "[uuid]",
                "org_id": "[uuid]",
                "application_id": "[uuid]",
                "created_at": "[timestamp]",
                "updated_at": "[timestamp]",
                "secret_prefix": "[redacted]",
                "secret_suffix": "[redacted]",
                "name": "second",
                "expires_at": None,
                "disabled_at": None,
                "last_used_at": None,
                "created_by_member_id": "[uuid]",
                "status": "active",
            },
            {
                "id": "[uuid]",
                "org_id": "[uuid]",
                "application_id": "[uuid]",
                "created_at": "[timestamp]",
                "updated_at": "[timestamp]",
                "secret_prefix": "[redacted]",
                "secret_suffix": "[redacted]",
                "name": "first",
                "expires_at": None,
                "disabled_at": None,
                "last_used_at": None,
                "created_by_member_id": "[uuid]",
                "status": "active",
            },
        ]
    )
    apps.secrets.delete(w.application.id, first.id)
    assert second.id != first.id

    # Signing keys: the application is created holding one, and a second
    # is added and revoked.
    keys = apps.keys.list(w.application.id)
    assert len(keys) == 1, "an application starts with one signing key"
    key = apps.keys.create(w.application.id)
    assert {k.id for k in apps.keys.list(w.application.id)} == {
        keys[0].id,
        key.id,
    }
    apps.keys.delete(w.application.id, key.id)

    # A service account signs nobody in, so it refuses an identity
    # provider; a federated application takes one, checked by its issuer.
    with pytest.raises(ValidationError):
        apps.idps.create(w.application.id, issuer=WALK.idp_issuer)
    federated = apps.create(
        name=f"{WALK.application_name}-federated",
        application_type="jwks",
        project=w.project.id,
    )
    idp = apps.idps.create(federated.id, issuer=WALK.idp_issuer)
    assert idp.issuer == WALK.idp_issuer
    assert [i.id for i in apps.idps.list(federated.id)] == [idp.id]
    apps.idps.delete(federated.id, idp.id)
    assert list(apps.idps.list(federated.id)) == []
    apps.delete(federated.id, project=w.project.id)


@walk_step(
    3, "repository — a hosted repository the walk pushes the recipe into"
)
def test_03_repository(world: World) -> None:
    w = world
    created = w.sa.repositories.create(
        WALK.recipe_slug, project=w.project.id, default_branch="main"
    )
    assert created.url, "the credential-free Git transport URL"
    assert stable(created) == snapshot(
        {
            "id": "[uuid]",
            "project_id": "[uuid]",
            "integration_id": None,
            "url": "[url]",
            "name": "hello-mcp",
            "slug": "hello-mcp",
            "provider": "introspection",
            "default_branch": "main",
            "provisioning_status": "pending",
            "seed_template": "pi-agent",
            "created_at": "[timestamp]",
            "pushed_at": None,
            "head_commit_sha": None,
            "is_recipe_source": False,
        }
    )

    # Provisioning seeds the hosted copy with the deployment's template; that
    # first push pins a recipe, and a runtime made from it registers the
    # group's slug, which lets the next push version the group.
    w.repository = settled(
        w.mode,
        lambda: w.sa.repositories.get(created.id, project=w.project.id),
        lambda: w.sa_quiet.repositories.get(created.id, project=w.project.id),
        lambda r: str(r.provisioning_status) in ("ready", "failed"),
        label="hosted repository",
    )
    assert str(w.repository.provisioning_status) == "ready"
    seeded = settled(
        w.mode,
        lambda: list(w.sa.recipes.list(project=w.project.id)),
        lambda: list(w.sa_quiet.recipes.list(project=w.project.id)),
        lambda rows: any(r.repository_id == w.repository.id for r in rows),
        label="seed recipe",
    )
    seed = next(r for r in seeded if r.repository_id == w.repository.id)
    seed_runtime = w.sa.runtimes.create(
        project=w.project.id,
        recipe_id=seed.id,
        name=WALK.runtime_slug,
        slug=WALK.runtime_slug,
    )
    assert seed_runtime.slug == WALK.runtime_slug

    if w.recipe_dir is not None:
        push_recipe(w.recipe_dir, created.url, w.member_token)

    listed = w.sa.repositories.list(
        project=w.project.id, slug=WALK.recipe_slug
    )
    assert any(r.id == w.repository.id for r in listed)


def _recipe_at(client: IntrospectionClient, project: UUID, sha: str) -> Any:
    return next(
        (
            r
            for r in client.recipes.list(project=project)
            if r.git_commit_sha == sha
        ),
        None,
    )


@walk_step(
    4,
    "recipe — create from the repository at a pinned commit, read, list, update",
)
def test_04_recipe(world: World) -> None:
    w = world
    repo = w.repository.id
    head = w.sa.repositories.commits(repo, sha="main").records[0]
    assert head.sha, "a commit on the hosted main"
    assert w.sa.repositories.commit(repo, head.sha).sha == head.sha
    branches = w.sa.repositories.branches(repo).page()
    assert any(b.name == "main" for b in branches.records)
    entry = w.sa.repositories.contents.get(
        repo, "agents/scripted.yaml", ref=head.sha
    )
    assert entry.path == "agents/scripted.yaml"
    root = w.sa.repositories.contents(repo, ref=head.sha)
    assert any(e.path == "judges" for e in root.records)

    # The push versioned the manifest's recipe at the pushed commit.
    w.recipe = settled(
        w.mode,
        lambda: _recipe_at(w.sa, w.project.id, head.sha),
        lambda: _recipe_at(w.sa_quiet, w.project.id, head.sha),
        lambda r: r is not None,
        label="push-versioned recipe",
    )
    # The slug ends in a hash of the pinned commit, which moves with the
    # recipe repository.
    assert re.fullmatch(
        r"hello-mcp-production-main-[0-9a-f]{12}", w.recipe.slug
    )
    assert stable({**plain(w.recipe), "slug": None}) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "repository_id": "[uuid]",
            "name": "hello-mcp",
            "slug": None,
            "git_ref": "main",
            "git_commit_sha": "[sha]",
            "sub_path": ".",
            "description": "Harbor E2B task calling a development MCP server",
            "created_by_member_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "git_commit_subject": None,
            "mcp_servers": [
                {
                    "id": "[redacted]",
                    "required": True,
                    "tools": {"include": ["echo"], "exclude": []},
                }
            ],
            "policies": None,
            "validation": {
                "status": "valid",
                "validator_name": "introspection-recipe-check",
                "validator_version": "0.12.0",
                "checked_at": "[timestamp]",
                "error_message": None,
                "diagnostics": [],
            },
        }
    )
    # A second pin of the same commit under the walk's own name: a sibling
    # of the push's row, not the same row.
    w.pinned_recipe = w.sa.recipes.create(
        project=w.project.id,
        repository_id=repo,
        name="hello-mcp (walk pin)",
        git_ref="main",
        git_commit_sha=head.sha,
    )
    assert w.pinned_recipe.git_commit_sha == head.sha
    assert w.pinned_recipe.id != w.recipe.id

    assert w.sa.recipes.get(w.recipe.id).slug == w.recipe.slug
    assert any(
        r.id == w.recipe.id for r in w.sa.recipes.list(project=w.project.id)
    )
    updated = w.sa.recipes.update(w.recipe.id, description="The walk's recipe")
    assert updated.description == "The walk's recipe"

    # A third pin, removed: `recipes:delete` is the owner's.
    doomed = w.sa.recipes.create(
        project=w.project.id,
        repository_id=repo,
        name="hello-mcp (walk, deleted)",
        git_ref="main",
        git_commit_sha=head.sha,
    )
    w.owner.recipes.delete(doomed.id, project=w.project.id)
    expect_not_found(lambda: w.sa.recipes.get(doomed.id))

    # A merge of a branch into itself has nothing to merge; the owner's
    # Data Plane token merges as its member.
    assert w.member.repositories.merges.create(repo, "main", "main") is None
    # A Git provider token is the grant of the runtime a sandbox runs on,
    # so a session with no runtime is refused.
    with pytest.raises(IntrospectionAPIError) as refused:
        w.member.repositories.access_token(repo)
    assert refused.value.status_code == 403


@walk_step(
    5,
    "credential and variable — a write-only secret and a value the sandbox "
    "reads",
)
def test_05_credential_and_variable(world: World) -> None:
    w = world
    credential = w.sa.credentials.create(
        name=WALK.credential_name,
        secret=WALK.credential_secret,
        project=w.project.id,
    )
    assert "secret" not in plain(credential), "a secret never reads back"
    assert stable(credential) == snapshot(
        {
            "runtime_id": None,
            "runtime_group_id": None,
            "environment": None,
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "name": "WALK_SECRET",
            "created_by_member_id": "[uuid]",
            "has_secret": True,
            "secret_display": "walk***0001",
            "secret_set_at": "[timestamp]",
        }
    )
    listed = w.sa.credentials.list(project=w.project.id)
    assert any(c.id == credential.id for c in listed)
    read = w.sa.credentials.get(credential.id, project=w.project.id)
    assert read.name == WALK.credential_name
    w.sa.credentials.update(
        credential.id,
        project=w.project.id,
        secret=f"{WALK.credential_secret}-rotated",
    )

    variable = w.sa.variables.create(
        name=WALK.variable_name,
        kind="value",
        value=WALK.variable_value,
        project=w.project.id,
    )
    assert stable(variable) == snapshot(
        {
            "runtime_id": None,
            "runtime_group_id": None,
            "environment": None,
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "name": "WALK_MARKER",
            "created_by_member_id": "[uuid]",
            "kind": "value",
            "value": "walk-marker-7f3a",
        }
    )
    listed_vars = w.sa.variables.list(project=w.project.id)
    assert any(v.id == variable.id for v in listed_vars)
    updated = w.sa.variables.update(
        variable.id, project=w.project.id, value=WALK.variable_value
    )
    assert updated.value == WALK.variable_value


@walk_step(6, "connector — the public MCP reference server, discovered")
def test_06_connector(world: World) -> None:
    w = world
    discovered = w.sa.connectors.discover_oauth(WALK.mcp_issuer)
    assert discovered.authorization_endpoint, "the issuer publishes metadata"
    # Naming the issuer alone makes the Control Plane discover the endpoints,
    # register a client dynamically and record PKCE support.
    w.connector = w.sa.connectors.create(
        name=WALK.connector_name,
        slug=WALK.connector_name,
        provider=WALK.connector_name,
        auth_mode="oauth_stored",
        issuer=WALK.mcp_issuer,
        api_hosts=["example-server.modelcontextprotocol.io"],
    )
    assert stable(w.connector) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "slug": "hello-mcp",
            "name": "hello-mcp",
            "provider": "hello-mcp",
            "auth_mode": "oauth_stored",
            "environment": "production",
            "agent_member_id": "[uuid]",
            "authorization_endpoint": "[url]",
            "token_endpoint": "[url]",
            "scopes": [],
            "api_hosts": ["example-server.modelcontextprotocol.io"],
            "client_id": "[uuid]",
            "person_server_url": None,
            "application_id": None,
            "assertion_audience": None,
            "policy_entities": None,
            "webhook_url": None,
            "status": "pending",
            "created_by_member_id": "[uuid]",
            "metadata": {
                "oauth": {
                    "resource": "[url]",
                    "client_registration": "dynamic",
                    "registration_endpoint": "[url]",
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                },
                "issuer": "[url]",
            },
            "requires_runtime": False,
        }
    )
    assert w.sa.connectors.get(w.connector.id).slug == WALK.connector_name
    assert any(c.id == w.connector.id for c in w.sa.connectors.list())
    updated = w.sa.connectors.update(
        w.connector.id, name=f"{WALK.connector_name} (walk)"
    )
    assert updated.name == f"{WALK.connector_name} (walk)"

    # The open MCP registry a custom connector picks from; a connector made
    # from an issuer has no provider catalogue of its own.
    listings = w.sa.connectors.search_custom_apps("everything", limit=5)
    assert all(app.name for app in listings)
    with pytest.raises(ValidationError):
        w.sa.connectors.list_apps(w.connector.id, query="mcp")

    # A connection registered with a caller-supplied token, read and
    # revoked before the OAuth grant makes the runtime's own.
    connections = w.sa.connectors.connections
    registered = connections.create(
        w.connector.id, access_token=WALK.registered_token
    )
    assert str(registered.status) == "active"
    assert connections.get(w.connector.id, registered.id).id == registered.id
    # `connectors:delete` is the owner's.
    w.owner.connectors.connections.revoke(w.connector.id, registered.id)
    expect_not_found(lambda: connections.get(w.connector.id, registered.id))


def _versioned(client: IntrospectionClient, w: World) -> Runtime | None:
    return next(
        (
            r
            for r in client.runtimes.list(
                project=str(w.project.id), runtime=WALK.runtime_slug
            )
            if r.recipe_id == w.recipe.id
        ),
        None,
    )


def _baked(r: Runtime | None) -> bool:
    return r is not None and r.image_build_status in (
        "ready",
        "failed",
    )


@walk_step(7, "runtime — created from the recipe and baked")
def test_07_runtime(world: World) -> None:
    w = world
    # The push versioned the group at the recipe's commit; that version is
    # the runtime the walk runs on, and the API creates the next one.
    runtime = settled(
        w.mode,
        lambda: _versioned(w.sa, w),
        lambda: _versioned(w.sa_quiet, w),
        _baked,
        label="push-versioned runtime bake",
        timeout=1800,
        interval=10,
    )
    assert runtime is not None
    w.runtime = runtime
    assert w.runtime.image_build_status == "ready"
    assert stable(w.runtime) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "name": "hello-mcp",
            "slug": "hello-mcp",
            "recipe_id": "[uuid]",
            "is_active": False,
            "description": "Harbor E2B task calling a development MCP server",
            "metadata": None,
            "llm_mode": "managed",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "yanked_at": None,
            "yanked_reason": None,
            "environment_ref": None,
            "runtime_group_type": "custom",
            "mcp_requirements": None,
            "template_ref": None,
            "image_revision": None,
            "image_commit_subject": None,
            "image_repository": None,
            "kind": "byor",
            "config_json": {"connectors": ["hello-mcp"]},
            "runtime_group_id": "[uuid]",
            "recipe_kind": "production",
            "recipe_ref": "main",
            "environments": ["staging", "production"],
            "image_build_status": "ready",
            "image_build_error_message": None,
            "image_build_metadata": {
                "image_tag": "[redacted]",
                "built_at": "[timestamp]",
                "size_bytes": "[number]",
                "external_image_name": "[redacted]",
                "verdict_by": "[timestamp]",
            },
            "created_by_member_id": "[uuid]",
        }
    )

    # A version's identity in its group is its recipe, so the next version
    # pins the walk's own recipe of the same commit.
    created = w.sa.runtimes.create(
        project=w.project.id,
        recipe_id=w.pinned_recipe.id,
        name=WALK.runtime_slug,
        slug=WALK.runtime_slug,
        config_json={"connectors": [WALK.connector_name]},
    )
    assert str(created.runtime_group_id) == w.group_id
    runtime_v2 = settled(
        w.mode,
        lambda: w.sa.runtimes.get(created.id),
        lambda: w.sa_quiet.runtimes.get(created.id),
        _baked,
        label="runtime bake",
        timeout=1800,
        interval=10,
    )
    assert runtime_v2 is not None
    w.runtime_v2 = runtime_v2
    assert w.runtime_v2.image_build_status == "ready"
    described = w.sa.runtimes.update(
        w.runtime_v2.id, description="the walk's own version"
    )
    assert described.description == "the walk's own version"
    # The list serves the group's live version, the newest one.
    assert any(
        str(r.runtime_group_id) == w.group_id
        for r in w.sa.runtimes.list(
            project=str(w.project.id), runtime=WALK.runtime_slug
        )
    )


@walk_step(
    8, "connection and endpoint — the grant binds hello-mcp to the runtime"
)
def test_08_connection_and_endpoint(world: World) -> None:
    w = world
    return_url = f"{w.settings.base_api_url}/walk/connected"
    started = w.sa.connectors.authorize(
        w.connector.id,
        runtime=UUID(w.group_id),
        return_url=return_url,
        binding={
            "environment": "production",
            "mcp_server_id": WALK.mcp_server_id,
            "url": WALK.mcp_endpoint,
        },
    )
    assert started.authorize_url
    landed = follow_authorization(
        started.authorize_url,
        base_api_url=w.settings.base_api_url,
        cookie=w.settings.cp_session,
        return_url=return_url,
    )
    assert landed.params.get("status") == "active"
    connection_id = landed.params["connection_id"]
    assert connection_id == IsUUID
    connection = w.sa.connectors.connections.get(
        w.connector.id, UUID(connection_id)
    )
    assert stable(connection) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "connector_id": "[uuid]",
            "member_id": None,
            "created_by_member_id": "[uuid]",
            "runtime_group_id": "[uuid]",
            "subject_type": "app",
            "scopes_granted": [],
            "status": "active",
            "token_expires_at": "[timestamp]",
            "provider_app": None,
            "provider_account_id": None,
        }
    )
    assert any(
        str(c.id) == connection_id
        for c in w.sa.connectors.connections.list(w.connector.id)
    )

    endpoints = w.sa.endpoints
    w.endpoint = (
        endpoints.list(project=w.project.id, mcp_server_id=WALK.mcp_server_id)
        .page()
        .records[0]
    )
    assert stable(w.endpoint) == snapshot(
        {
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "org_id": "[uuid]",
            "id": "[uuid]",
            "name": "hello-mcp",
            "host": "example-server.modelcontextprotocol.io",
            "base_url": "[url]",
            "kind": "mcp",
            "metadata": {
                "mcp_server_id": "hello-mcp",
                "connector_id": "[uuid]",
                "provider_app": None,
                "extra_hosts": [],
                "auth_audience": None,
            },
            "assertion_claims": None,
            "runtime_id": None,
            "runtime_group_id": "[uuid]",
            "environment": "production",
            "verify_path": None,
            "project_id": "[uuid]",
            "headers": {},
            "header_names": [],
            "credential_refs": [],
            "last_verified_at": None,
            "authorized_application_id": None,
            "created_by_member_id": "[uuid]",
        }
    )
    read = endpoints.get(w.endpoint.id, project=w.project.id)
    assert read.kind == "mcp"
    renamed = endpoints.update(
        w.endpoint.id, project=w.project.id, name="hello-mcp (walk)"
    )
    assert renamed.name == "hello-mcp (walk)"

    # A plain upstream API, created and deleted; with no `verify_path` the
    # Control Plane calls nothing.
    api = endpoints.create(
        project=w.project.id,
        name=WALK.api_endpoint_name,
        host=WALK.api_endpoint_host,
        kind="api",
        headers={"X-Walk": f"${{{WALK.credential_name}}}"},
    )
    assert (api.host, str(api.kind)) == (WALK.api_endpoint_host, "api")
    assert api.credential_refs == [WALK.credential_name]
    endpoints.delete(api.id, project=w.project.id)
    expect_not_found(lambda: endpoints.get(api.id, project=w.project.id))

    # The app connection is the runtime group's; the broker resolves it
    # from the connector and the service account's project.
    token = w.sa.connectors.connections.get_token(w.connector.id)
    assert stable(token) == snapshot(
        {
            "token": "[redacted]",
            "token_type": "bearer",
            "expires_at": "[timestamp]",
            "scopes": [],
        }
    )

    requirements = w.sa.runtimes.get(
        w.runtime.id, include=[RuntimeInclude.MCP_REQUIREMENTS]
    )
    assert stable(requirements.mcp_requirements) == snapshot([])


def _ids(files: Iterable[File]) -> list[str]:
    return [str(f.id) for f in files]


@walk_step(9, "files in — an upload the task will find under /workspace/files")
def test_09_files_in(world: World) -> None:
    w = world
    w.input_file = w.sa.files.create_text(
        name=WALK.input_file_name,
        content=WALK.input_file_text,
        mime_type="text/plain",
        metadata={"suite": "walk"},
    )
    assert stable(w.input_file) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "name": "walk-input.txt",
            "file_type": "filesystem",
            "storage_path": "[uuid]/[uuid]/files/[uuid]/walk-input.txt",
            "mime_type": "text/plain",
            "metadata": {
                "suite": "walk",
                "blob_checksum": "[digest]",
                "original_filename": "walk-input.txt",
            },
            "member_id": "[uuid]",
            "size_bytes": "[number]",
            "version": 1,
            "parent_id": None,
            "storage_version_id": None,
            "task_id": None,
            "tags": [],
            "generated_output_task_id": None,
            "expires_at": None,
        }
    )
    file_id = str(w.input_file.id)
    assert w.sa.files.get(file_id).name == WALK.input_file_name
    assert w.sa.files.download(file_id).decode() == WALK.input_file_text
    version = w.sa.files.versions.create(
        file_id,
        file=io.BytesIO(f"{WALK.input_file_text} (v2)".encode()),
        name=WALK.input_file_name,
        content_type="text/plain",
    )
    assert any(v.id == version.id for v in w.sa.files.versions.list(file_id))
    w.sa.files.versions.get(file_id, str(version.id))
    updated = w.sa.files.update(
        file_id, metadata={"suite": "walk", "stage": "attached"}
    )
    assert (updated.metadata or {}).get("stage") == "attached"
    files = w.sa.files
    # A file with versions is listed only with `include_versions`.
    tagged = files.list(
        include_versions=True,
        metadata={"suite": "walk", "stage": "attached"},
    ).page()
    assert file_id in _ids(tagged.records), "the metadata filter finds it"
    files.update(file_id, tags=["suite:walk"])
    by_tag = files.list(tag="suite:walk", include_versions=True).page()
    assert file_id in _ids(by_tag.records), "the tag filter finds the file"
    by_name = files.list(name_contains="WALK-INPUT", include_versions=True)
    assert file_id in _ids(by_name.page().records), "the substring filter"


def _idle(task: Task) -> bool:
    return str(task.status) in IDLE


@walk_step(
    10,
    "task — a runner on the runtime, one turn that calls the MCP and leaves "
    "a file",
)
def test_10_task(world: World) -> None:
    w = world
    w.runner = w.sa.runtimes.handle(w.runtime.id).run(
        agent_name=w.settings.agent, ttl_seconds=None
    )
    tasks = w.runner.tasks
    started = tasks.start(
        prompt=prompt(w.settings),
        agent_name=w.settings.agent,
        files=[{"id": str(w.input_file.id)}],
        metadata={"suite": "walk"},
        idle_timeout_seconds=180,
    )
    assert started.task is not None, "the create returns the task"
    assert len(started.text()) > 0, "the turn replied"
    task_id = str(started.task.id)

    # The stream ends before the row settles; the second turn needs it idle.
    w.task = settled(
        w.mode,
        lambda: tasks.get(task_id),
        lambda: w.sa_quiet.tasks.get(task_id),
        _idle,
        label="task after its first turn",
        timeout=120,
        interval=2,
    )
    # `metadata` is the platform's and differs between a warm pod and a baked
    # image; the walk's own key is asserted and the rest left out.
    assert (w.task.metadata or {}).get("suite") == "walk"
    assert stable({**plain(w.task), "metadata": None}) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "title": "Call the `echo` tool from the declared `hello-mcp` MCP server with the message `hello from the public MCP`. Write the echoed value exactly, with no quotes or additional formatting, to `/workspace/outputs/greeting.txt`. Then run `echo $WALK_MARKER` in…",
            "display_index": "[number]",
            "kind": "agent",
            "status": "idle",
            "member_id": "[uuid]",
            "automation_id": None,
            "runtime_id": "[uuid]",
            "is_archived": False,
            "started_at": "[timestamp]",
            "completed_at": None,
            "last_user_message_at": "[timestamp]",
            "metadata": None,
            "conversation_metadata": None,
            "agent": None,
            "tags": [],
            "runtime_group_id": "[uuid]",
        }
    )
    w.conversation_id = str(
        (w.task.metadata or {}).get("conversation_id") or w.task.id
    )
    run = tasks.runs.get(task_id, started.run.id)
    assert str(run.task_id) == task_id

    tasks.runs.create(task_id, prompt={"text": second_turn(w.settings)}).text()
    settled(
        w.mode,
        lambda: tasks.get(task_id),
        lambda: w.sa_quiet.tasks.get(task_id),
        _idle,
        label="task after its second turn",
        timeout=120,
        interval=2,
    )
    third = tasks.runs.create(
        task_id, prompt={"text": second_turn(w.settings)}
    )
    third.cancel()
    settled(
        w.mode,
        lambda: tasks.get(task_id),
        lambda: w.sa_quiet.tasks.get(task_id),
        lambda t: str(t.status) in (*IDLE, "cancelled"),
        label="task after a cancelled turn",
        timeout=120,
        interval=2,
    )
    assert any(str(t.id) == task_id for t in tasks.list())
    retitled = tasks.update(task_id, title="The walk's task")
    assert retitled.title == "The walk's task"
    tasks.archive(task_id)
    tasks.unarchive(task_id)


def _task_files(client: IntrospectionClient, task_id: str) -> list[File]:
    return client.files.list(task_id=task_id).page().records


@walk_step(11, "evidence — the output file, the conversation and its items")
def test_11_evidence(world: World) -> None:
    w = world
    task_id = str(w.task.id)
    outputs = settled(
        w.mode,
        lambda: _task_files(w.sa, task_id),
        lambda: _task_files(w.sa_quiet, task_id),
        lambda files: any(
            f.name.endswith(WALK.output_file_name) for f in files
        ),
        label="task output files",
        timeout=120,
    )
    w.output_file = next(
        f for f in outputs if f.name.endswith(WALK.output_file_name)
    )
    assert stable(w.output_file) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "name": "tasks/[uuid]/outputs/greeting.txt",
            "file_type": "filesystem",
            "storage_path": "[uuid]/[uuid]/files/[uuid]/greeting.txt",
            "mime_type": "text/plain",
            "metadata": {
                "task_id": "[uuid]",
                "blob_checksum": "[digest]",
                "relative_path": "greeting.txt",
                "conversation_id": "[uuid]",
                "original_filename": "greeting.txt",
            },
            "member_id": "[uuid]",
            "size_bytes": "[number]",
            "version": 1,
            "parent_id": None,
            "storage_version_id": None,
            "task_id": "[uuid]",
            "tags": [],
            "generated_output_task_id": "[uuid]",
            "expires_at": None,
        }
    )
    content = w.sa.files.download(str(w.output_file.id)).decode()
    assert content.strip() == WALK.echo_result

    conversations = w.sa.conversations
    cid = w.conversation_id
    conversation = settled(
        w.mode,
        lambda: conversations.get(cid),
        lambda: w.sa_quiet.conversations.get(cid),
        lambda _: True,
        label="conversation",
    )
    assert stable(conversation) == snapshot(
        {
            "object": "conversation",
            "id": "[uuid]",
            "task_title": "The walk's task",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "agents": [{"id": "[redacted]", "name": "scripted", "depth": 0}],
            "usage": {
                "total_input_tokens": "[number]",
                "output_tokens": "[number]",
                "total_tokens": "[number]",
            },
            "cost": {"usd": 0.0},
            "metrics": {
                "duration_ms": "[number]",
                "trace_count": "[number]",
                "max_turn": "[number]",
                "span_count": "[number]",
                "tool_use_count": "[number]",
                "failed_tool_use_count": "[number]",
                "llm_call_count": "[number]",
                "failed_llm_call_count": "[number]",
                "has_errors": False,
            },
            "environment": "production",
            "service_name": "hello-mcp",
            "runtime": {"id": "[uuid]", "group_id": "[uuid]"},
            "recipe": {"git_commit_sha": "[sha]"},
            "owner": {"key": "[redacted]"},
        }
    )
    metrics = conversation.metrics
    assert metrics.llm_call_count == IsPositiveInt
    assert metrics.tool_use_count == IsPositiveInt
    assert metrics.trace_count == IsInt(ge=2)
    assert conversation.usage.total_tokens == IsPositiveInt

    # The SDK's default page (100) is not the route's (200); the route's
    # default sends the request the recording holds.
    page = settled(
        w.mode,
        lambda: conversations.items.list(cid, limit=200).page(),
        lambda: w.sa_quiet.conversations.items.list(cid, limit=200).page(),
        lambda p: "echo" in p.model_dump_json()
        and WALK.variable_value in p.model_dump_json(),
        label="conversation items",
        timeout=120,
        interval=5,
    )
    items = page.model_dump_json()
    assert "echo" in items, "the hello-mcp echo tool was called"
    assert WALK.echo_result in items, (
        "the echo result reached the conversation"
    )
    assert WALK.variable_value in items, "the variable reached the sandbox"
    first = page.data[0]
    conversations.items.get(cid, str(first.span_id))
    assert any(
        c.id == cid
        for c in conversations.list(runtime_group_id=UUID(w.group_id))
    )
    assert conversations.export_trajectory(cid), "the trajectory export"

    # The other export formats, the Arrow list, and a paged item list.
    # `retrieve(cid)` scans a bounded page of 50 items for the latest turn
    # (`LATEST_TURN_SCAN_LIMIT`) where the JS SDK reads the route's default
    # page, so the scan differs on the wire; the walk reads the route's page
    # and names the turn the same rule finds.
    scan = conversations.items.list(cid, limit=200).page()
    turn = next(
        (
            i
            for i in scan.data
            if i.attributes.gen_ai
            and i.attributes.gen_ai.operation
            and i.attributes.gen_ai.operation.name == "chat"
        ),
        None,
    )
    assert turn is not None
    latest = conversations.retrieve(cid, str(turn.span_id))
    assert latest is not None and latest.span_id, "the latest LLM turn"
    exported = conversations.export_json(cid)
    assert len(exported.data) >= len(page.data)
    # Spans can still be arriving between two exports, so each is held to
    # the items the step already read rather than to the other.
    table = conversations.export_arrow(cid)
    assert table.num_rows >= len(page.data)
    streamed = json.loads(b"".join(conversations.export_stream(cid, "json")))
    assert len(streamed["data"]) >= len(page.data)
    listed = conversations.list_arrow(
        runtime_group_id=UUID(w.group_id)
    ).read_all()
    assert listed.num_rows > 0
    pages = 0
    for _ in conversations.items.list(cid, limit=1):
        pages += 1
        if pages == 2:
            break
    assert pages == 2, "a second page of items"
    # `contains` selects items by the plaintext summary of their messages.
    tool_calls = conversations.items.list(
        cid, limit=200, contains=["gen_ai.output.messages.parts.name:*"]
    ).page()
    assert "echo" in tool_calls.model_dump_json(), "a tool-call item"
    user_turns = conversations.items.list(
        cid, limit=200, contains=["gen_ai.input.messages.role:user"]
    ).page()
    assert len(user_turns.data) > 0, "a user turn"


@walk_step(
    12,
    "the dev lane — introspection dev serves a local MCP into a development "
    "task",
)
def test_12_dev_lane(world: World) -> None:
    # The CLI serves its login's project; pending a project flag. Live only
    # and CLI-only (design doc §4), as in the JS walk.
    pytest.skip("the dev lane is CLI-only and not recorded (design doc §4)")


@walk_step(
    13, "telemetry reads — metrics, a tag, a share, an annotation, events"
)
def test_13_telemetry_reads(world: World) -> None:
    w = world
    # A fixed window, so the request replays; the walk's conversation is
    # within it by construction.
    metrics = w.sa.metrics.query(
        {
            "view": "conversations",
            "metrics": [{"aggregation": "count"}],
            "filters": [
                {
                    "field": "runtime_id",
                    "operator": "eq",
                    "value": str(w.runtime.id),
                },
            ],
            "from_timestamp": "2026-01-01T00:00:00Z",
            "to_timestamp": "2027-01-01T00:00:00Z",
        }
    )
    assert metrics, "a metrics response"

    # Access tags are an administrator's to write: the owner's token, not
    # the service account, which acts as the project's agent member.
    member_quiet = w.quiet(
        token=w.member_token,
        base_api_url=w.settings.base_api_url,
        dp_url=str(w.sa._dp_http._client.base_url),
    )
    tag = w.member.tags.create(
        AccessTagCreate(name="walk", description="the walk's tag")
    )
    assert stable(tag) == snapshot(
        {
            "kind": "access",
            "name": "walk",
            "color": None,
            "description": "the walk's tag",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
        }
    )
    w.member.tags.get(TagKind.ACCESS, "walk")
    w.member.tags.update(
        TagKind.ACCESS,
        "walk",
        TagUpdate(description="the walk's tag, updated"),
    )
    assert any(t.name == "walk" for t in w.member.tags.list(TagKind.ACCESS))

    # A tag share's grantor must hold the tag, so the file is shared to the
    # owner member directly.
    owners = list(w.owner.members.list())
    share = w.sa.shares.create(
        resource_type="file",
        resource_id=str(w.output_file.id),
        granted_member_id=str(owners[0].id),
    )
    assert stable(share) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "resource_type": "file",
            "resource_id": "[uuid]",
            "granted_member_id": "[uuid]",
            "granted_tag": None,
            "visible_from": None,
            "created_by_member_id": "[uuid]",
            "url": "[url]",
        }
    )
    w.sa.shares.get(str(share.id))
    # `visible_from` is a conversation share's; a file share takes only a
    # clear.
    assert w.sa.shares.update(str(share.id), visible_from=None).id == share.id
    assert any(
        s.id == share.id for s in w.sa.shares.list(resource_type="file")
    )

    # The annotation targets the conversation's first item (its span).
    cid = w.conversation_id
    target = w.sa.conversations.items.list(cid, limit=200).page().data[0]
    assert target.trace_id and target.span_id
    span = {"trace_id": target.trace_id, "span_id": target.span_id}
    # An event id derived from the span, so the request replays; the SDK
    # would mint one.
    w.member.annotations.create(
        **span,
        labels=["walk"],
        event_id=span_event_id(target.trace_id, target.span_id, "labels"),
    )
    # Reviewers by email resolve through the Control Plane's member list,
    # which a member's Data Plane token cannot read; the walk clears them,
    # which needs no lookup, and reaches the check made before any request.
    w.member.annotations.create(
        **span,
        reviewer_emails=[],
        event_id=span_event_id(target.trace_id, target.span_id, "reviewers"),
    )
    with pytest.raises(ValidationError):
        w.member.annotations.create(
            trace_id=target.trace_id,
            span_id=target.span_id,
            reviewer_emails=[" "],
        )
    annotations = settled(
        w.mode,
        lambda: list(w.member.annotations.list(conversation_id=cid)),
        lambda: list(member_quiet.annotations.list(conversation_id=cid)),
        lambda rows: len(rows) > 0 or w.settings.target == "compose",
        label="annotations",
        timeout=60,
    )
    # An annotation reads back once the processor has landed it; on the
    # local stack it stays `visible: false`, a finding the design doc records.
    if w.settings.target != "compose":
        assert "walk" in (annotations[0].labels or [])

    def annotation_events(client: IntrospectionClient) -> list[Any]:
        return list(
            client.events.list("introspection.annotation", conversation_id=cid)
        )

    events = settled(
        w.mode,
        lambda: annotation_events(w.sa),
        lambda: annotation_events(w.sa_quiet),
        lambda rows: len(rows) > 0 or w.settings.target == "compose",
        label="annotation events",
        timeout=60,
    )
    # The local stack never makes an annotation visible, so its event is
    # read where it landed and is a 404 where it did not.
    if events:
        w.sa.events.get(str(events[0].id))
    else:
        labels = span_event_id(target.trace_id, target.span_id, "labels")
        expect_not_found(lambda: w.sa.events.get(str(labels)))
    event_table = w.sa.events.list_arrow(
        "introspection.annotation", conversation_id=cid
    ).read_all()
    assert event_table.num_rows >= len(events)
    facets = w.member.annotations.facets()
    assert facets is not None
    assert (
        w.member.annotations.navigation(
            trace_id=target.trace_id, span_id=target.span_id
        )
        is not None
    )

    # The AAuth surfaces, read empty: no agent has asked for anything, so
    # there is no mission or approval to read or decide.
    assert w.sa.aauth.missions.list().page().records == []
    assert w.sa.aauth.approvals.list().page().records == []
    expect_not_found(lambda: w.sa.aauth.missions.get(NIL))
    expect_not_found(lambda: w.sa.aauth.approvals.get(NIL))
    expect_not_found(
        lambda: w.sa.aauth.approvals.decide(
            NIL, status="denied", member_id=owners[0].id
        )
    )
    # `/v1/connections` holds the project's own grant from step 8, with no
    # member; an app connector is what a member connects through, which
    # needs that provider's credentials, so with none on the project the
    # other routes answer 404 (member-connections.md).
    missing = "019a1000-0000-7000-8000-0000000000c1"
    project_grant = next(
        c
        for c in w.member.connections.list(connector_id=w.connector.id)
        if str(c.owner) == "project"
    )
    assert project_grant.member_id is None
    assert project_grant.connector is not None
    assert project_grant.connector.slug == WALK.connector_name
    expect_not_found(lambda: w.member.connections.get(missing))
    expect_not_found(lambda: w.member.connections.delete(missing))
    expect_not_found(
        lambda: w.member.connections.create(
            app="gmail", runtime=WALK.runtime_slug
        )
    )
    # A client with no runtime of its own cannot omit one: the Python SDK
    # makes `runtime` required on the client (the runner defaults it), so
    # the JS walk's "refuses before any request" is a signature here.


@walk_step(
    14,
    "eval — a trial on the runtime, graded by the recipe's judge; an "
    "experiment over two versions",
)
def test_14_eval(world: World) -> None:
    w = world
    # What eval compose services run as, and the org's provider installs.
    images = w.sa.images.list().page()
    if images.records:
        w.sa.images.get(images.records[0].id)
    # A mirror needs no upload: recording it queues the copy, and a
    # service image is removed whatever its build has reached.
    mirror = w.sa.images.create(
        name=WALK.image_name,
        source={"kind": "mirror", "reference": WALK.image_reference},
    )
    assert w.sa.images.get(mirror.id).name == WALK.image_name
    w.sa.images.delete(mirror.id)
    list(w.owner.integrations.list())
    judges = w.sa.judges.list(
        project=w.project.id, runtime_group_id=UUID(w.group_id)
    )
    w.judge = next(j for j in judges if j.name == "greeting")
    assert w.sa.judges.get(w.judge.id, project=w.project.id).name == "greeting"
    w.sa.judges.update(
        w.judge.id, project=w.project.id, enabled=True, sample_rate=1
    )

    # A trial needs the evals capability, which the runner's session never
    # carries; the service account holds `tasks:eval` and names the runtime.
    created = w.sa.tasks.create(
        kind="eval",
        runtime_id=w.runtime.id,
        commands=True,
        prompt=prompt(w.settings),
        agent_name=w.settings.agent,
        metadata={"suite": "walk"},
        idle_timeout_seconds=120,
    )
    w.eval_task = created.task
    assert (w.eval_task.metadata or {}).get("suite") == "walk"
    assert stable({**plain(w.eval_task), "metadata": None}) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "title": "Call the `echo` tool from the declared `hello-mcp` MCP server with the message `hello from the public MCP`. Write the echoed value exactly, with no quotes or additional formatting, to `/workspace/outputs/greeting.txt`. Then run `echo $WALK_MARKER` in…",
            "display_index": "[number]",
            "kind": "eval",
            "status": "pending",
            "member_id": "[uuid]",
            "automation_id": None,
            "runtime_id": "[uuid]",
            "is_archived": False,
            "started_at": None,
            "completed_at": None,
            "last_user_message_at": "[timestamp]",
            "metadata": None,
            "conversation_metadata": None,
            "agent": {"sandbox_status": "provisioning", "session_id": None},
            "tags": [],
            "runtime_group_id": "[uuid]",
        }
    )
    # Read the run's stream to its end, then let the row settle.
    for _ in w.sa.tasks.runs.stream(str(w.eval_task.id), created.run.id):
        pass
    eval_id = str(w.eval_task.id)
    w.eval_task = settled(
        w.mode,
        lambda: w.sa.tasks.get(eval_id),
        lambda: w.sa_quiet.tasks.get(eval_id),
        lambda t: str(t.status) in (*IDLE, "failed"),
        label="the trial",
    )
    assert str(w.eval_task.status) in IDLE

    def experiment(name: str) -> dict[str, Any]:
        return {
            "name": name,
            "project": str(w.project.id),
            "runtime_group_id": w.group_id,
            "goal_json": {
                "kind": "composite",
                "components": [
                    {
                        "source": "judge",
                        "judge_id": str(w.judge.id),
                        "weight": 1,
                    },
                ],
            },
            "arms": [
                {"runtime_id": str(w.runtime.id), "arm_label": "v1"},
                {"runtime_id": str(w.runtime_v2.id), "arm_label": "v2"},
            ],
        }

    experiments = w.sa.experiments
    w.experiment = experiments.create(experiment(WALK.experiment_names[0]))
    assert stable(w.experiment) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "name": "The walk's experiment",
            "runtime_group_id": "[uuid]",
            "environment": "production",
            "status": "draft",
            "routing_strategy": "beta_sample",
            "arms": [
                {
                    "runtime_id": "[uuid]",
                    "arm_label": "v1",
                    "agent_overrides": None,
                    "id": "[uuid]",
                    "initial_weight": 50,
                },
                {
                    "runtime_id": "[uuid]",
                    "arm_label": "v2",
                    "agent_overrides": None,
                    "id": "[uuid]",
                    "initial_weight": 50,
                },
            ],
            "goal_json": {
                "kind": "composite",
                "direction": "maximize",
                "components": [
                    {
                        "source": "judge",
                        "judge_id": "[uuid]",
                        "judge_definition_hash": "[digest]",
                        "weight": 1.0,
                        "guard": None,
                    }
                ],
            },
            "scoring_interval_seconds": 300,
            "hash_key_fields": ["user.id", "anonymous.id", "conversation.id"],
            "sample_rate": 1.0,
            "description": None,
            "posterior_json": None,
            "weights_json": None,
            "started_at": None,
            "ended_at": None,
            "halted_at": None,
            "halted_reason": None,
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "created_by_member_id": "[uuid]",
            "archived_at": None,
        }
    )
    experiments.get(w.experiment.id)
    experiments.update(
        w.experiment.id, {"description": "two versions, one judge"}
    )
    handle = experiments(w.experiment.id)
    assert str(handle.start().status) == "running"
    assert any(
        e.id == w.experiment.id
        for e in experiments.list(project=str(w.project.id))
    )
    # Bandit routing needs a stable subject to assign an arm to.
    runner = handle.run(
        identity={"user_id": "sdk-walk-user"}, ttl_seconds=None
    )
    assert runner, "a runner on the experiment"
    ended = handle.end()
    assert stable(ended) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "name": "The walk's experiment",
            "runtime_group_id": "[uuid]",
            "environment": "production",
            "status": "ended",
            "routing_strategy": "beta_sample",
            "arms": [
                {
                    "runtime_id": "[uuid]",
                    "arm_label": "v1",
                    "agent_overrides": None,
                    "id": "[uuid]",
                    "initial_weight": 50,
                },
                {
                    "runtime_id": "[uuid]",
                    "arm_label": "v2",
                    "agent_overrides": None,
                    "id": "[uuid]",
                    "initial_weight": 50,
                },
            ],
            "goal_json": {
                "kind": "composite",
                "direction": "maximize",
                "components": [
                    {
                        "source": "judge",
                        "judge_id": "[uuid]",
                        "judge_definition_hash": "[digest]",
                        "weight": 1.0,
                        "guard": None,
                    }
                ],
            },
            "scoring_interval_seconds": 300,
            "hash_key_fields": ["user.id", "anonymous.id", "conversation.id"],
            "sample_rate": 1.0,
            "description": "two versions, one judge",
            "posterior_json": None,
            "weights_json": None,
            "started_at": "[timestamp]",
            "ended_at": "[timestamp]",
            "halted_at": None,
            "halted_reason": None,
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "created_by_member_id": "[uuid]",
            "archived_at": None,
        }
    )
    second = experiments.create(experiment(WALK.experiment_names[1]))
    experiments(second.id).start()
    assert str(experiments(second.id).cancel().status) == "cancelled"
    w.owner.experiments.delete(second.id, project=str(w.project.id))


@walk_step(15, "commands — exec and download inside the eval's sandbox")
def test_15_commands(world: World) -> None:
    w = world
    eval_id = str(w.eval_task.id)
    commands = w.sa.tasks.commands

    def command(spec: dict[str, Any]) -> Any:
        created = commands.create(eval_id, spec)
        return settled(
            w.mode,
            lambda: commands.get(eval_id, created.id),
            lambda: w.sa_quiet.tasks.commands.get(eval_id, created.id),
            lambda c: str(c.status)
            in ("succeeded", "completed", "failed", "cancelled"),
            label="task command",
            timeout=120,
        )

    output = f"/workspace/outputs/{WALK.output_file_name}"
    exec_ = command(
        {"kind": "exec", "command": ["cat", output], "timeout_seconds": 30}
    )
    assert stable(exec_) == snapshot(
        {
            "id": "[uuid]",
            "task_id": "[uuid]",
            "kind": "exec",
            "spec": {
                "cwd": None,
                "kind": "exec",
                "command": ["cat", "/workspace/outputs/greeting.txt"],
                "service": None,
                "timeout_seconds": 30,
            },
            "status": "completed",
            "exit_code": 0,
            "stdout": "Echo: hello from the public MCP",
            "stderr": "",
            "output_file_id": None,
            "error": None,
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "started_at": "[timestamp]",
            "finished_at": "[timestamp]",
        }
    )
    assert (exec_.stdout or "").strip() == WALK.echo_result
    download = command({"kind": "download", "path": output})
    assert download.output_file_id, "the download produced a file"
    assert len(commands.list(eval_id).page().records) >= 2

    # Judging runs in the sandbox at teardown and calls the judge's grader
    # through the egress; on the scripted target that grader returns no
    # verdict, so a judgement is asserted only where a real model grades.
    def judgements(client: IntrospectionClient) -> list[Any]:
        return (
            client.events.list(
                IntrospectionEventName.JUDGEMENT, judge_id=w.judge.id
            )
            .page()
            .records
        )

    rows = settled(
        w.mode,
        lambda: judgements(w.sa),
        lambda: judgements(w.sa_quiet),
        lambda rows: len(rows) > 0 or w.settings.agent == "scripted",
        label="judgement",
        timeout=1800,
        interval=10,
    )
    if w.settings.agent != "scripted":
        assert len(rows) > 0, "the recipe's judge graded the trial"


@walk_step(16, "automations — a manual automation, triggered")
def test_16_automations(world: World) -> None:
    w = world
    automations = w.sa.automations
    automation = automations.create(
        name=WALK.automation_name,
        trigger_type="manual",
        prompt=second_turn(w.settings),
        runtime_group_id=UUID(w.group_id),
        # An automation its owner creates posts into that owner's own task;
        # the first task was archived and unarchived, which the trigger
        # still refuses, so the trial is the one it posts into.
        task_id=w.eval_task.id,
    )
    assert stable(automation) == snapshot(
        {
            "id": "[uuid]",
            "name": "The walk's automation",
            "trigger_type": "manual",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "description": None,
            "enabled": True,
            "cron_schedule": None,
            "kind": None,
            "prompt": 'Reply with the single word done. <<SCRIPT {"reply":"done"}>>',
            "metadata": None,
            "tags": [],
            "last_triggered_at": None,
            "next_trigger_at": None,
            "runtime_group_id": "[uuid]",
            "task_id": "[uuid]",
            "agent_member_id": None,
            "created_by_member_id": "[uuid]",
            "execution_blocked_reason": None,
            "can_manage": True,
            "owner_role": "operator",
            "created_at": "[timestamp]",
            "updated_at": "[timestamp]",
            "deleted_at": None,
        }
    )
    triggered = automations.trigger(automation.id)
    assert stable(triggered) == snapshot(
        {
            "status": "triggered",
            "automation_id": "[uuid]",
            "task_id": "[uuid]",
            "reason": None,
        }
    )
    automations.get(automation.id)
    automations.update(automation.id, description="triggered once by the walk")
    assert any(a.id == automation.id for a in automations.list())


@dataclass
class Person:
    id: str
    client: Any


def _can(read: Any) -> bool:
    try:
        read()
    except NotFoundError:
        return False
    return True


NONE = {"conversation": False, "task": False, "file": False, "output": False}
ALL = {"conversation": True, "task": True, "file": True, "output": True}
#: Casey holds one of the task's two tags, which opens the task and its
#: conversation; the output file carries no tags of its own, so a tag
#: reader cannot open it.
BY_TAG = {"conversation": True, "task": True, "file": False, "output": False}


def _persona(w: World, name: str, tags: list[str]) -> Person:
    external_user_id = f"user:walk-{name}"
    # Members have no public delete, so a persona from an earlier run is
    # reused and its name and tags set again.
    existing = (
        w.owner.members.list(
            member_type=MemberType.CUSTOMER,
            external_user_id=[external_user_id],
        )
        .page()
        .records
    )
    if existing:
        member_id = str(existing[0].id)
        w.owner.members.update(existing[0].id, name=name.title(), tags=tags)
    else:
        member_id = str(
            w.owner.members.create(
                CustomerMemberCreate(
                    external_user_id=external_user_id,
                    name=name.title(),
                    tags=tags,
                )
            ).id
        )
    client = w.sa.runtimes.handle(w.runtime.id).run(
        agent_name=w.settings.agent,
        identity={"user_id": f"walk-{name}"},
        ttl_seconds=None,
    )
    return Person(member_id, client)


@walk_step(
    17,
    "access — Avery's work, read by Blake (a member share), Casey (the "
    "platform group tag), Drew (an administrator) and Emery (only a "
    "project-wide share)",
)
def test_17_access(world: World) -> None:
    w = world
    # The owner login is privileged, so its quiet client polls for what
    # Avery makes; every person's own read is then recorded once.
    owner_quiet = w.quiet(
        token=w.member_token,
        base_api_url=w.settings.base_api_url,
        dp_url=w.settings.dp_url,
    )
    # Drew, the administrator: an application bound to the organisation's
    # admin agent member, whose client-credentials token is privileged.
    admin_agent = next(
        m.id
        for m in w.owner.members.list(member_type="agent")
        if str(m.role) == "admin"
    )
    drew_app = w.owner.applications.create(
        name=WALK.admin_name,
        application_type="service_account",
        allowed_scopes=[
            "conversations:read",
            "tasks:read",
            "files:read",
            "shares:read",
            "shares:delete",
        ],
        agent_member_id=admin_agent,
        project=w.project.id,
    )
    drew_secret = w.owner.applications.secrets.create(drew_app.id, name="drew")
    assert drew_secret.secret is not None
    drew_token = service_account_token(
        client_id=drew_app.client_id,
        client_secret=drew_secret.secret.get_secret_value(),
        project=str(w.project.id),
        base_api_url=w.settings.base_api_url,
    )
    drew = IntrospectionClient(
        token=drew_token.access_token,
        base_api_url=w.settings.base_api_url,
        dp_url=drew_token.dp_url,
    )
    people = {
        name: _persona(w, name, tags) for name, tags in WALK.personas.items()
    }
    avery, blake = people["avery"], people["blake"]

    # Avery makes everything first: a task tagged for the platform group,
    # its conversation and output file, and a file of their own.
    started = avery.client.tasks.start(
        prompt=prompt(w.settings),
        agent_name=w.settings.agent,
        metadata={"suite": "walk"},
        conversation_metadata={"suite": "walk", "persona": "avery"},
        tags=[WALK.group_tag, "suite:walk"],
        idle_timeout_seconds=180,
    )
    started.text()
    task_id = str(started.task.id)
    avery_task = settled(
        w.mode,
        lambda: avery.client.tasks.get(task_id),
        lambda: owner_quiet.tasks.get(task_id),
        _idle,
        label="Avery's task",
        timeout=300,
        interval=5,
    )
    assert avery_task.tags == [WALK.group_tag, "suite:walk"]
    # A row carrying two tags is found by either one.
    for tag in (WALK.group_tag, "suite:walk"):
        assert any(
            str(t.id) == task_id for t in w.member.tasks.list(tag=tag)
        ), f"the task list by {tag}"
    assert avery_task.conversation_metadata == {
        "suite": "walk",
        "persona": "avery",
    }
    conversation = task_id
    outputs = settled(
        w.mode,
        lambda: _task_files(w.member, task_id),
        lambda: _task_files(owner_quiet, task_id),
        lambda files: any(
            f.name.endswith(WALK.output_file_name) for f in files
        ),
        label="Avery's output",
        timeout=120,
    )
    output_id = str(
        next(f.id for f in outputs if f.name.endswith(WALK.output_file_name))
    )
    settled(
        w.mode,
        lambda: w.member.conversations.get(conversation),
        lambda: owner_quiet.conversations.get(conversation),
        lambda c: c.metrics.llm_call_count > 0,
        label="Avery's conversation",
        timeout=120,
        interval=5,
    )
    avery_file = str(
        avery.client.files.create_text(
            name=WALK.persona_file_name,
            content="Avery's notes",
            mime_type="text/plain",
            metadata={"suite": "walk"},
        ).id
    )
    # Both keys must sit on the conversation (ANDed).
    assert any(
        c.id == conversation
        for c in w.member.conversations.list(
            metadata={"suite": "walk", "persona": "avery"}
        )
    ), "conversation_metadata filters"

    def reads(client: Any) -> dict[str, bool]:
        return {
            "conversation": _can(
                lambda: client.conversations.get(conversation)
            ),
            "task": _can(lambda: client.tasks.get(task_id)),
            "file": _can(lambda: client.files.get(avery_file)),
            "output": _can(lambda: client.files.get(output_id)),
        }

    def matrix() -> dict[str, dict[str, bool]]:
        return {
            "avery": reads(avery.client),
            "blake": reads(blake.client),
            "casey": reads(people["casey"].client),
            "drew": reads(drew),
            "emery": reads(people["emery"].client),
        }

    before = {
        "avery": ALL,
        "blake": NONE,
        "casey": BY_TAG,
        "drew": ALL,
        "emery": NONE,
    }
    assert matrix() == before, "before any share"

    # A share to one member, and one to everyone holding the group tag.
    shares = avery.client.shares
    to_blake = shares.create(
        resource_type="conversation",
        resource_id=conversation,
        granted_member_id=blake.id,
    )
    to_platform = shares.create(
        resource_type="file",
        resource_id=avery_file,
        granted_tag=WALK.group_tag,
    )
    assert matrix() == {
        "avery": ALL,
        # A conversation share opens the conversation, never the task.
        "blake": {**NONE, "conversation": True},
        "casey": {**BY_TAG, "file": True},
        "drew": ALL,
        "emery": NONE,
    }, "a member share and a tag share"

    # A share naming neither opens the conversation to the whole project.
    to_project = shares.create(
        resource_type="conversation", resource_id=conversation
    )
    assert matrix()["emery"] == {
        **NONE,
        "conversation": True,
    }, "a project-wide share"

    # Revoked, every share stops granting. A runner cannot hold
    # `shares:delete`, so the administrator revokes Avery's shares.
    for share in (to_blake, to_platform, to_project):
        drew.shares.delete(str(share.id))
    assert matrix() == before, "every share revoked"

    w.member.files.delete(avery_file)
    w.member.tasks.delete(task_id)
    w.owner.applications.delete(drew_app.id, project=w.project.id)


def sign_in_routes(w: World) -> None:
    """What `introspection login`, `logout` and `dev` reach through the SDK,
    short of a person approving in a browser: a device code and one poll
    that finds it pending, a refresh and a development credential the
    server refuses (only an approved login holds what they take), a
    revocation and a sign-out that name no session (the owner's own would
    end the walk's), and the remote connection's protocol. The WebSocket
    itself is not opened: attaching needs a development login."""
    base = w.settings.base_api_url
    device = request_device_code(base_api_url=base)
    assert device.verification_uri_complete.startswith(device.verification_uri)
    poll = poll_device_token(
        device.device_code.get_secret_value(), base_api_url=base
    )
    assert (poll.status, poll.token) == (DeviceTokenStatus.PENDING, None)
    with pytest.raises(ValidationError) as refused:
        refresh_access_token(
            "walk-no-refresh-token",
            DEVICE_FLOW_CLIENT_ID,
            str(NIL),
            str(NIL),
            base_api_url=base,
        )
    assert refused.value.code == "invalid_grant"
    with pytest.raises(ValidationError) as refused:
        development_credential("walk-not-a-login", base_api_url=base)
    assert refused.value.code == "invalid_grant"
    revoke_session(
        str(NIL), str(NIL), DEVICE_FLOW_CLIENT_ID, base_api_url=base
    )
    oidc_logout("walk-no-session", base_api_url=base)

    docs = w.member.remotes.connect_docs()
    assert docs.endpoint == "/v1/remotes/connect"
    assert any(
        f.frame == "attach_request"
        for f in docs.message_protocol.remote_to_cloud
    )


@walk_step(
    18,
    "members and keys — the owner's reads, a development API key, the "
    "organisation",
)
def test_18_members_and_keys(world: World) -> None:
    w = world
    members = list(w.owner.members.list())
    assert len(members) > 0
    w.owner.members.get(members[0].id)
    org = w.owner.organizations.me()
    # An invite outlives the project, so a repeat run finds the one the last
    # run sent; the address names this organisation, since a person belongs
    # to one and a second organisation's walk would answer 409.
    email = f"walk-member@{org.slug}.example.com"
    invite = {"email": email, "name": "Walk member", "role": "member"}
    invited = next((m for m in members if m.email == email), None)
    if invited is None:
        invited = w.owner.members.create(invite)
    else:
        with pytest.raises(ConflictError):
            w.owner.members.create(invite)
    assert invited.email == email
    assert str(invited.role) == "member"
    renamed = w.owner.members.update(invited.id, name="Walk member (renamed)")
    assert renamed.name == "Walk member (renamed)"
    me = w.owner.oidc.me()
    assert str(me.org_id) == str(w.project.org_id)
    sign_in_routes(w)
    # The project offers no runtime group to another project.
    peerings = w.owner.projects.peerings
    assert list(peerings.list(w.project.id)) == []
    expect_not_found(lambda: peerings.get(w.project.id, NIL))
    api_key = w.sa.api_keys.create(
        project=w.project.id,
        name=WALK.api_key_name,
        environment="development",
        allow=["runtimes"],
    )
    assert api_key.api_key, "the plaintext key is returned once"
    assert stable({**plain(api_key), "api_key": None}) == snapshot(
        {
            "id": "[uuid]",
            "org_id": "[uuid]",
            "project_id": "[uuid]",
            "created_at": "[timestamp]",
            "name": "walk",
            "environment": "development",
            "allow": ["runtimes"],
            "scope": "telemetry:write projects:read repositories:read recipes:read recipes:write runtimes:read runtimes:write experiments:read experiments:write tasks:read tasks:write tasks:delete files:read files:write conversations:read events:read metrics:read shares:read shares:write shares:delete connectors:read connectors:write annotations:read approvals:read approvals:write",
            "member_id": "[uuid]",
            "key_prefix": "[redacted]",
            "key_suffix": "[redacted]",
            "redacted_key": "[redacted]",
            "status": "active",
            "expires_at": None,
            "last_used_at": None,
            "acknowledged_at": None,
            "key_display": "[redacted]",
            "prefix": "[redacted]",
            "api_key": None,
        }
    )
    # The key list is its own envelope, `api_keys`, not a page.
    keys = w.sa.api_keys.list(project=w.project.id)
    assert any(k.id == api_key.id for k in keys)
    w.sa.api_keys.update(
        api_key.id, project=w.project.id, name=f"{WALK.api_key_name} (renamed)"
    )
    w.sa.api_keys.acknowledge(api_key.id, project=w.project.id)
    # The organisation's name and slug are whoever is running the walk.
    assert org.slug
    assert stable({**plain(org), "name": None, "slug": None}) == snapshot(
        {
            "id": "[uuid]",
            "name": None,
            "slug": None,
            "external_org_id": "[id]",
            "image_url": None,
            "hosted_git": True,
        }
    )


@walk_step(19, "teardown — everything the walk created, in reverse")
def test_19_teardown(world: World, cassette: Cassette | None) -> None:
    w = world
    # The default file list omits the upload a task holds, so it goes by id.
    w.sa.files.delete(str(w.input_file.id))
    remove_walk_resources(w.owner, w.member, w.project, dp=w.sa)
    expect_not_found(lambda: w.sa.tasks.get(str(w.task.id)))
    expect_not_found(lambda: w.sa.files.get(str(w.input_file.id)))
    expect_not_found(lambda: w.sa.runtimes.get(w.runtime_v2.id))
    expect_not_found(lambda: w.sa.connectors.get(w.connector.id))
    expect_not_found(lambda: w.sa.recipes.get(w.recipe.id))
    expect_not_found(
        lambda: w.owner.applications.get(
            w.application.id, project=w.project.id
        )
    )
    # The walk's project goes with it; the login's is untouched.
    w.owner.projects.delete(w.project.id)
    expect_not_found(lambda: w.owner.projects.get(str(w.project.id)))
    assert (
        w.owner.projects.get(str(w.login_project.id)).id == w.login_project.id
    )
    if w.mode == "replay" and cassette is not None:
        # Every recorded exchange was asked for: a call the SDK stopped
        # making leaves its entry behind.
        unplayed = [
            f"{request.method} {request.uri}"
            for i, (request, _) in enumerate(cassette.data)
            if not cassette.play_counts[i]
        ]
        assert unplayed == [], "recorded requests the walk never sent"
