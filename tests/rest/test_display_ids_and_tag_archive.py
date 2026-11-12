"""Contract tests for the fields the v0.84.0 server added: project display
ID prefixes, an issue's display key and warnings, a recipe's agents and
issue providers, a tag's rename archive, a runtime's commit and an
organization's sign-in settings and a run caller's timezone.

Each response is decoded strict, so a field the SDK does not model fails
here before it fails the walk."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from introspection_sdk._strict_schema import STRICT_SCHEMA_ENV
from introspection_sdk.resources import (
    Organizations,
    Projects,
    Recipes,
    Runtimes,
)
from introspection_sdk.resources.tags import AsyncTags, Tags
from introspection_sdk.runner_resources.issues import Issues
from introspection_sdk.schemas.organizations import (
    PasskeyRequirement,
    SignInSettings,
)
from introspection_sdk.schemas.projects import (
    DisplayIdPrefixes,
    DisplayIdPrefixesUpdate,
)
from introspection_sdk.schemas.tags import TagInclude, TagKind

from .conftest import (
    RECIPE_ID,
    RUNTIME_ID,
    FakeAPI,
    recipe_payload,
    runner_spec_payload,
    runtime_payload,
    to_jsonable,
)
from .test_annotations import label
from .test_issues import issue_body
from .test_project_writes import DEPLOYMENT_ID, ORGANIZATION, project

PREFIXES = {"issue": "BUG", "report": "R", "observation": "F", "task": "T"}


@pytest.fixture(autouse=True)
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STRICT_SCHEMA_ENV, "1")


def test_a_project_reads_its_display_id_prefixes(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/projects/support",
        json_body=project(display_id_prefixes=PREFIXES),
    )
    read = Projects(fake_api.client()).get("support")
    assert read.display_id_prefixes == DisplayIdPrefixes(issue="BUG")


def test_a_project_without_prefixes_reads_the_defaults(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/projects/support", json_body=project())
    read = Projects(fake_api.client()).get("support")
    assert read.display_id_prefixes == DisplayIdPrefixes(
        issue="I", report="R", observation="F", task="T"
    )


def test_create_and_update_send_display_id_prefixes(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/projects",
        status=201,
        json_body=project(display_id_prefixes=PREFIXES),
    )
    fake_api.add(
        "PATCH",
        "/v1/projects/support",
        json_body=project(display_id_prefixes={**PREFIXES, "task": "JOB"}),
    )
    projects = Projects(fake_api.client())
    projects.create(
        name="Support",
        deployment_id=UUID(DEPLOYMENT_ID),
        display_id_prefixes=DisplayIdPrefixes(issue="BUG"),
    )
    assert fake_api.requests[0].json()["display_id_prefixes"] == PREFIXES

    updated = projects.update(
        "support", display_id_prefixes=DisplayIdPrefixesUpdate(task="JOB")
    )
    assert updated.display_id_prefixes.task == "JOB"
    # A prefix left unset keeps its current value, so only the one given goes.
    assert fake_api.last_request.json() == {
        "display_id_prefixes": {"task": "JOB"}
    }


def test_an_issue_reads_its_display_key_and_filters_by_it(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/issues",
        json_body={
            "records": [issue_body(display_key="BUG-42")],
            "next": None,
            "count": 1,
        },
    )
    issues = list(Issues(fake_api.client()).list(display_key="BUG-42"))
    assert [issue.display_key for issue in issues] == ["BUG-42"]
    assert fake_api.last_request.params.multi_items() == [
        ("display_key", "BUG-42")
    ]


def test_an_issue_without_a_display_index_has_no_display_key(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        "/v1/issues",
        json_body={
            "records": [issue_body(display_index=None, display_key=None)],
            "next": None,
            "count": 1,
        },
    )
    [issue] = list(Issues(fake_api.client()).list())
    assert issue.display_key is None


def test_a_recipe_reads_its_agents_and_issue_providers(fake_api: FakeAPI):
    body = to_jsonable(recipe_payload())
    fake_api.add(
        "GET",
        f"/v1/recipes/{RECIPE_ID}",
        json_body={
            **body,
            "agents": ["agent", "triage"],
            "issue_providers": ["linear"],
        },
    )
    recipe = Recipes(fake_api.client()).get(UUID(RECIPE_ID))
    assert recipe.agents == ["agent", "triage"]
    assert recipe.issue_providers == ["linear"]


def test_an_unchecked_recipe_has_no_agents(fake_api: FakeAPI):
    body = to_jsonable(recipe_payload())
    fake_api.add(
        "GET",
        f"/v1/recipes/{RECIPE_ID}",
        json_body={**body, "agents": None, "issue_providers": None},
    )
    recipe = Recipes(fake_api.client()).get(UUID(RECIPE_ID))
    assert recipe.agents is None
    assert recipe.issue_providers is None


def archived(name: str, replaced_by: str) -> dict[str, object]:
    return {
        **label(),
        "name": name,
        "archived_at": "2026-11-01T09:00:00Z",
        "replaced_by": replaced_by,
        "archived_names": [],
    }


def test_a_tag_list_with_archived_reads_the_rename(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tags",
        json_body={
            "records": [
                {
                    **label(),
                    "archived_at": None,
                    "replaced_by": None,
                    "archived_names": ["review-needed"],
                },
                archived("review-needed", "needs-review"),
            ],
            "next": None,
            "count": 2,
        },
    )
    live, old = list(
        Tags(fake_api.client()).list(
            TagKind.ANNOTATION, include=[TagInclude.ARCHIVED]
        )
    )
    assert fake_api.last_request.params.multi_items() == [
        ("kind", "annotation"),
        ("include", "archived"),
    ]
    assert live.archived_at is None
    assert live.archived_names == ["review-needed"]
    assert old.archived_at == datetime(2026, 11, 1, 9, tzinfo=UTC)
    assert old.replaced_by == "needs-review"


def test_a_tag_from_an_older_server_reads_no_archive(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tags",
        json_body={
            "records": [label()],
            "next": None,
            "count": 1,
        },
    )
    [tag] = list(Tags(fake_api.client()).list(TagKind.ANNOTATION))
    assert "include" not in fake_api.last_request.params
    assert tag.archived_at is None
    assert tag.replaced_by is None
    assert tag.archived_names == []


async def test_async_tag_list_sends_include(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tags",
        json_body={
            "records": [archived("review-needed", "needs-review")],
            "next": None,
            "count": 1,
        },
    )
    page = await AsyncTags(fake_api.async_client()).list(
        TagKind.ANNOTATION, include=[TagInclude.ARCHIVED]
    )
    assert page.records[0].replaced_by == "needs-review"
    assert fake_api.last_request.params.get_list("include") == ["archived"]


def test_a_runtime_reads_its_commit_and_filters_by_ref_and_commit(
    fake_api: FakeAPI,
):
    sha = "0123456789abcdef0123456789abcdef01234567"
    body = to_jsonable(runtime_payload())
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body={
            "records": [{**body, "git_commit_sha": sha}],
            "count": 1,
            "next": None,
        },
    )
    [runtime] = list(
        Runtimes(fake_api.client()).list(recipe_ref="main", git_commit_sha=sha)
    )
    assert runtime.git_commit_sha == sha
    params = fake_api.last_request.params
    assert (params["recipe_ref"], params["git_commit_sha"]) == ("main", sha)


def test_a_runtime_without_a_recipe_has_no_commit(fake_api: FakeAPI):
    body = to_jsonable(runtime_payload())
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body={
            "records": [{**body, "git_commit_sha": None}],
            "count": 1,
            "next": None,
        },
    )
    [runtime] = list(Runtimes(fake_api.client()).list())
    assert runtime.git_commit_sha is None
    assert "git_commit_sha" not in fake_api.last_request.params


def test_an_organization_reads_its_sign_in_settings(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/organizations/me",
        json_body={
            **ORGANIZATION,
            "sign_in": {
                "passkey_requirement": "except_sso",
                "restrict_invites_to_domains": True,
            },
        },
    )
    org = Organizations(fake_api.client()).me()
    assert org.sign_in == SignInSettings(
        passkey_requirement=PasskeyRequirement.EXCEPT_SSO,
        restrict_invites_to_domains=True,
    )


def test_a_new_passkey_requirement_reads_as_its_string(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/organizations/me",
        json_body={
            **ORGANIZATION,
            "sign_in": {
                "passkey_requirement": "hardware_key",
                "restrict_invites_to_domains": False,
            },
        },
    )
    org = Organizations(fake_api.client()).me()
    assert org.sign_in is not None
    assert org.sign_in.passkey_requirement == "hardware_key"


def test_an_organization_without_enterprise_sign_in(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/organizations/me", json_body=ORGANIZATION)
    assert Organizations(fake_api.client()).me().sign_in is None


def test_an_issue_reads_the_warnings_of_a_capped_read(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/issues",
        json_body={
            "records": [issue_body(warnings=["comments beyond 50 left out"])],
            "count": 1,
            "next": None,
        },
    )
    [issue] = list(Issues(fake_api.client()).list())
    assert issue.warnings == ["comments beyond 50 left out"]


def test_a_run_reads_the_callers_timezone_back(fake_api: FakeAPI):
    spec = to_jsonable(runner_spec_payload())
    spec["runtime_context"]["caller"] = {"timezone": "Europe/London"}
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body={
            "records": [to_jsonable(runtime_payload())],
            "count": 1,
            "next": None,
        },
    )
    fake_api.add("POST", f"/v1/runtimes/{RUNTIME_ID}/run", json_body=spec)
    runner = Runtimes(fake_api.client())(UUID(RUNTIME_ID)).run(
        caller={"timezone": "Europe/London"}
    )
    assert fake_api.last_request.json()["caller"] == {
        "timezone": "Europe/London"
    }
    assert runner.context.caller is not None
    assert runner.context.caller.timezone == "Europe/London"
