"""Tests for ``client.runtimes`` (:mod:`introspection_sdk.resources.runtimes`).

All HTTP is served by the in-process transport in ``conftest.py``.
"""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from introspection_sdk.resources.runtimes import (
    Runtimes,
    _looks_like_uuid,
)
from introspection_sdk.runner import Runner
from introspection_sdk.schemas.recipes import Recipe
from introspection_sdk.schemas.runtimes import RuntimeCreate

from .conftest import (
    PROJECT_ID,
    RECIPE_ID,
    RUNTIME_ID,
    FakeAPI,
    paginated,
    recipe_payload,
    runner_spec_payload,
    runtime_payload,
    to_jsonable,
)


def _runtimes(fake_api: FakeAPI) -> Runtimes:
    return Runtimes(fake_api.client())


def test_looks_like_uuid():
    assert _looks_like_uuid(RUNTIME_ID)
    assert not _looks_like_uuid("checkout-agent")


def test_list_validates_and_drops_none_params(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    page = _runtimes(fake_api).list(project_id=PROJECT_ID, only_active=True)
    assert page.count == 1
    assert str(page.records[0].id) == RUNTIME_ID
    params = fake_api.last_request.params
    assert params.get("project_id") == PROJECT_ID
    assert params.get("only_active") == "true"
    assert "name" not in params  # None filtered out


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
    names = [r.name for r in _runtimes(fake_api).list(project_id=PROJECT_ID)]
    assert names == ["a", "b"]
    # The cursor from page 1 must be sent on the page-2 request; without
    # this a client that never forwarded ``next`` would still pass.
    assert seen_next == [None, "cursor-2"]


def test_get_includes_project_id(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/runtimes/{RUNTIME_ID}", json_body=runtime_payload()
    )
    rt = _runtimes(fake_api).get(RUNTIME_ID, project_id=PROJECT_ID)
    assert str(rt.id) == RUNTIME_ID
    assert fake_api.last_request.params.get("project_id") == PROJECT_ID


def test_create_from_model_excludes_none(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/runtimes", json_body=runtime_payload())
    _runtimes(fake_api).create(
        RuntimeCreate(project_id=UUID(PROJECT_ID), name="checkout-agent")
    )
    body = fake_api.last_request.json()
    assert body["name"] == "checkout-agent"
    assert "description" not in body  # exclude_none


def test_create_from_dict_drops_none(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/runtimes", json_body=runtime_payload())
    _runtimes(fake_api).create(
        {"project_id": PROJECT_ID, "name": "x", "description": None}
    )
    assert "description" not in fake_api.last_request.json()


def test_update_patches(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/runtimes/{RUNTIME_ID}",
        json_body=runtime_payload(name="renamed"),
    )
    rt = _runtimes(fake_api).update(RUNTIME_ID, {"name": "renamed"})
    assert rt.name == "renamed"
    assert fake_api.last_request.method == "PATCH"


def test_handle_with_uuid_skips_name_resolution(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )
    runtimes = _runtimes(fake_api)
    runner = runtimes(RUNTIME_ID).run()
    assert isinstance(runner, Runner)
    # No list call happened — only the /run POST.
    assert [r.path for r in fake_api.requests] == [
        f"/v1/runtimes/{RUNTIME_ID}/run"
    ]


def test_handle_resolves_name_via_list(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload()]),
    )
    runtimes = _runtimes(fake_api)
    handle = runtimes("checkout-agent")
    assert handle.runtime_id == RUNTIME_ID
    assert fake_api.last_request.params.get("name") == "checkout-agent"


def test_handle_name_not_found_raises(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/runtimes", json_body=paginated([]))
    handle = _runtimes(fake_api)("missing")
    with pytest.raises(LookupError, match="No active runtime"):
        _ = handle.runtime_id


def test_handle_ambiguous_name_raises(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload(), runtime_payload()]),
    )
    handle = _runtimes(fake_api)("dup")
    with pytest.raises(LookupError, match="Ambiguous"):
        _ = handle.runtime_id


def test_resolve_by_name_returns_runtime(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload()]),
    )
    runtime = _runtimes(fake_api).resolve_by_name(
        "checkout-agent", project_id=PROJECT_ID
    )
    assert str(runtime.id) == RUNTIME_ID
    params = fake_api.last_request.params
    assert params.get("name") == "checkout-agent"
    assert params.get("only_active") == "true"
    assert params.get("project_id") == PROJECT_ID


def test_resolve_by_name_not_found_raises(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/runtimes", json_body=paginated([]))
    with pytest.raises(LookupError, match="No active runtime"):
        _runtimes(fake_api).resolve_by_name("missing")


def test_resolve_by_name_ambiguous_raises(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload(), runtime_payload()]),
    )
    with pytest.raises(LookupError, match="Ambiguous"):
        _runtimes(fake_api).resolve_by_name("dup")


def test_run_returns_runner_with_context(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )
    runtimes = _runtimes(fake_api)
    runner = runtimes(RUNTIME_ID).run(
        identity={"user_id": "u1"}, caller={"locale": "en"}
    )
    assert runner.session_id == "sess-1"
    assert runner.dp_endpoint == "https://dp.test"
    body = fake_api.last_request.json()
    assert body["identity"]["user_id"] == "u1"
    assert body["caller"]["locale"] == "en"
    assert body["ttl_seconds"] == 3600


def test_pin_injects_recipe_id_on_run(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )
    recipe = Recipe.model_validate(recipe_payload())
    runtimes = _runtimes(fake_api)
    runtimes(RUNTIME_ID).pin(recipe).run()
    assert fake_api.last_request.json()["recipe_id"] == RECIPE_ID


def test_activate(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/activate",
        json_body=runtime_payload(is_active=True),
    )
    runtimes = _runtimes(fake_api)
    # No client-level default project: the per-call override is the only way
    # to scope activate to a specific project.
    rt = runtimes(RUNTIME_ID).activate(project_id=PROJECT_ID)
    assert rt.is_active is True
    assert fake_api.last_request.json()["project_id"] == PROJECT_ID
