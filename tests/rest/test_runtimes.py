"""Tests for ``client.runtimes`` (:mod:`introspection_sdk.resources.runtimes`).

All HTTP is served by the in-process transport in ``conftest.py``.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from introspection_sdk.resources.runtimes import Runtimes
from introspection_sdk.runner import Runner

from .conftest import (
    PROJECT_ID,
    REPOSITORY_ID,
    RUNTIME_ID,
    FakeAPI,
    paginated,
    runner_spec_payload,
    runtime_payload,
    to_jsonable,
)


def _runtimes(fake_api: FakeAPI) -> Runtimes:
    return Runtimes(fake_api.client())


def test_list_validates_and_drops_none_params(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    page = _runtimes(fake_api).list(project=PROJECT_ID)
    assert page.count == 1
    assert str(page.records[0].id) == RUNTIME_ID
    params = fake_api.last_request.params
    assert params.get("project") == PROJECT_ID
    assert "only_active" not in params
    assert "name" not in params
    assert "runtime" not in params


def test_iter_follows_pagination(fake_api: FakeAPI):
    pages = iter(
        [
            paginated([runtime_payload(name="a")], next="cursor-2"),
            paginated([runtime_payload(name="b")]),
        ]
    )
    seen_next: list[str | None] = []

    def _handler(req: httpx.Request) -> httpx.Response:
        seen_next.append(req.url.params.get("next"))
        return httpx.Response(200, json=to_jsonable(next(pages)))

    fake_api.add_handler("GET", "/v1/runtimes", _handler)
    names = [r.name for r in _runtimes(fake_api).list(project=PROJECT_ID)]
    assert names == ["a", "b"]
    # The cursor from page 1 must be sent on the page-2 request; without
    # this a client that never forwarded ``next`` would still pass.
    assert seen_next == [None, "cursor-2"]


def test_get_includes_project_param(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/runtimes/{RUNTIME_ID}", json_body=runtime_payload()
    )
    rt = _runtimes(fake_api).get(UUID(RUNTIME_ID), project=PROJECT_ID)
    assert str(rt.id) == RUNTIME_ID
    assert fake_api.last_request.params.get("project") == PROJECT_ID


def test_handle_with_uuid_sends_stable_runtime_group(fake_api: FakeAPI):
    runtime_group_id = UUID("33333333-3333-3333-3333-333333333333")
    fake_api.add(
        "POST",
        "/v1/runtimes/run",
        json_body=runner_spec_payload(),
    )
    runtimes = _runtimes(fake_api)
    runner = runtimes.run(runtime=runtime_group_id)
    assert isinstance(runner, Runner)
    assert [r.path for r in fake_api.requests] == ["/v1/runtimes/run"]
    assert fake_api.requests[0].json()["runtime"] == str(runtime_group_id)


def test_handle_sends_slug_directly(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/runtimes/run",
        json_body=runner_spec_payload(),
    )
    _runtimes(fake_api).run(runtime="checkout-agent", project=PROJECT_ID)
    assert fake_api.last_request.json()["runtime"] == "checkout-agent"
    assert fake_api.last_request.json()["project"] == PROJECT_ID


def test_list_versions_filters_by_stable_runtime(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload()]),
    )
    runtime = (
        _runtimes(fake_api)
        .list(runtime="checkout-agent", project=PROJECT_ID)
        .page()
        .records[0]
    )
    assert str(runtime.id) == RUNTIME_ID
    assert fake_api.last_request.params.get("runtime") == "checkout-agent"
    assert fake_api.last_request.params.get("project") == PROJECT_ID


def test_run_returns_runner_with_context(fake_api: FakeAPI):
    runtime_group_id = UUID("33333333-3333-3333-3333-333333333333")
    fake_api.add(
        "POST",
        "/v1/runtimes/run",
        json_body=runner_spec_payload(),
    )
    runtimes = _runtimes(fake_api)
    runner = runtimes.run(
        runtime=runtime_group_id,
        identity={"user_id": "u1"},
        caller={"locale": "en"},
        agent_name="support",
        scope="tasks:read tasks:write",
    )
    assert runner.session_id == "sess-1"
    assert runner.dp_endpoint == "https://dp.test"
    body = fake_api.last_request.json()
    assert body["identity"]["user_id"] == "u1"
    assert body["caller"]["locale"] == "en"
    assert body["agent_name"] == "support"
    assert "ttl_seconds" not in body
    assert body["scope"] == "tasks:read tasks:write"
    assert body["runtime"] == str(runtime_group_id)
    assert str(runner.context.runtime_group_id) == (
        "88888888-8888-8888-8888-888888888888"
    )
    assert str(runner.context.recipe_repository_id) == REPOSITORY_ID


def test_run_uses_runtime_id_field(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/runtimes/run", json_body=runner_spec_payload())
    runner = _runtimes(fake_api).run(
        runtime_id=UUID(RUNTIME_ID),
        project=PROJECT_ID,
        environment="staging",
    )
    assert isinstance(runner, Runner)
    assert fake_api.last_request.json()["runtime_id"] == RUNTIME_ID
    assert fake_api.last_request.json()["environment"] == "staging"
    assert runner.context.recipe_git_commit_sha == "abc123"
    assert runner.context.agent_name == "agent"


def test_runtime_version_matches_public_cloud_shape():
    runtime = runtime_payload(
        description="Published support agent",
        kind="byoh",
        llm_mode="byok",
        config_json={"timeout": 60},
        recipe_kind="preview",
        recipe_ref="pr/42",
        environments=["development", "staging"],
        image_tag="sha-abc123",
        image_status="ready",
        environment_ref={"development": "main", "staging": "pr/42"},
    )
    payload = runtime.model_dump(mode="json")

    assert payload["created_by_member_id"]
    assert payload["kind"] == "byoh"
    assert payload["llm_mode"] == "byok"
    assert payload["recipe_kind"] == "preview"
    assert payload["environments"] == ["development", "staging"]
    assert payload["environment_ref"] == {
        "development": "main",
        "staging": "pr/42",
    }
    assert "metadata" not in payload


def test_direct_stable_run_matches_handle(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/runtimes/run", json_body=runner_spec_payload())
    runner = _runtimes(fake_api).run(
        runtime="checkout-agent",
        project=PROJECT_ID,
        environment="production",
    )
    assert isinstance(runner, Runner)
    assert fake_api.last_request.json()["runtime"] == "checkout-agent"
    assert fake_api.last_request.json()["project"] == PROJECT_ID


def test_runtime_surface_excludes_operator_controls(fake_api: FakeAPI):
    runtimes = _runtimes(fake_api)
    for method in ("create", "update", "yank", "unyank"):
        assert not hasattr(runtimes, method)
    for method in ("pin", "activate"):
        assert not hasattr(runtimes, method)
