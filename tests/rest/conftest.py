"""Shared fixtures for the REST / Runner surface tests.

These are **offline contract/unit tests** for the SDK's client side.
They drive the REST namespaces through :class:`httpx.MockTransport`
backed by a small route table: the handler runs real Python and returns
genuine :class:`httpx.Response` instances, and nothing in
``introspection_sdk`` is patched or stubbed (no ``MagicMock`` / ``patch``
/ ``monkeypatch`` of SDK or HTTP internals). Response fixtures are built
from the SDK's own typed schemas, so they are schema-valid by
construction.

Scope and honesty about what this does *not* do: ``MockTransport`` is
not a ``pytest-recording`` cassette, so these tests do **not** verify
the live Introspection wire contract — only that the SDK builds the
right request (method / path / params / body / headers) and parses a
well-formed response correctly. The canned bodies encode our assumption
of the server contract; real-API drift is caught by the live
``-m integration`` job in ``ci.yml``, not here. The longer-term plan in
``AGENTS.md`` is to back the happy paths with recorded cassettes once a
live backend/token is available in CI; until then these stay framed as
contract tests rather than recordings.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.schemas.experiments import Experiment
from introspection_sdk.schemas.files import File, FileType
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.recipes import Recipe
from introspection_sdk.schemas.runner import (
    RunnerContext,
    RunnerDeployment,
    RunnerSpec,
)
from introspection_sdk.schemas.runtimes import Runtime
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelResponse,
    TaskCreateResponse,
    TaskRun,
    TaskRunResponse,
    TaskStatus,
)

# --- Fixed identifiers reused across payloads -----------------------

ORG_ID = "00000000-0000-0000-0000-0000000000aa"
PROJECT_ID = "00000000-0000-0000-0000-0000000000bb"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
RUNTIME_ID = "11111111-1111-1111-1111-111111111111"
EXPERIMENT_ID = "22222222-2222-2222-2222-222222222222"
RECIPE_ID = "33333333-3333-3333-3333-333333333333"
REPOSITORY_ID = "44444444-4444-4444-4444-444444444444"
TASK_ID = "55555555-5555-5555-5555-555555555555"
FILE_ID = "66666666-6666-6666-6666-666666666666"


# --- In-process transport -------------------------------------------


@dataclass
class CapturedRequest:
    """A request the fake API saw, for post-hoc assertions."""

    method: str
    url: httpx.URL
    headers: httpx.Headers
    content: bytes

    @property
    def path(self) -> str:
        return self.url.path

    @property
    def params(self) -> httpx.QueryParams:
        return self.url.params

    def json(self) -> Any:
        return _json.loads(self.content) if self.content else None


_Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeAPI:
    """A route table served over a real ``httpx.MockTransport``."""

    routes: dict[tuple[str, str], _Handler] = field(default_factory=dict)
    requests: list[CapturedRequest] = field(default_factory=list)

    def add(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeAPI:
        def _factory(_request: httpx.Request) -> httpx.Response:
            kwargs: dict[str, Any] = {}
            if json_body is not None:
                kwargs["json"] = to_jsonable(json_body)
            elif content is not None:
                kwargs["content"] = content
            return httpx.Response(
                status, headers=dict(headers or {}) or None, **kwargs
            )

        self.routes[(method.upper(), path)] = _factory
        return self

    def add_handler(
        self, method: str, path: str, handler: _Handler
    ) -> FakeAPI:
        self.routes[(method.upper(), path)] = handler
        return self

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._dispatch)

    def client(self, **kwargs: Any) -> _HttpClient:
        kwargs.setdefault("api_url", "https://api.test")
        kwargs.setdefault("token", "test-token")
        return _HttpClient(transport=self.transport(), **kwargs)

    def async_client(self, **kwargs: Any) -> _AsyncHttpClient:
        # ``httpx.MockTransport`` implements both the sync and async
        # transport protocols, so the same route table backs both clients.
        kwargs.setdefault("api_url", "https://api.test")
        kwargs.setdefault("token", "test-token")
        return _AsyncHttpClient(transport=self.transport(), **kwargs)

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            CapturedRequest(
                method=request.method,
                url=request.url,
                headers=request.headers,
                content=request.content,
            )
        )
        route = self.routes.get((request.method.upper(), request.url.path))
        if route is None:
            return httpx.Response(
                404,
                json={
                    "detail": f"no route for "
                    f"{request.method} {request.url.path}"
                },
            )
        return route(request)

    @property
    def last_request(self) -> CapturedRequest:
        return self.requests[-1]


@pytest.fixture
def fake_api() -> FakeAPI:
    return FakeAPI()


# --- Sample wire payloads -------------------------------------------
#
# Built from the SDK's own typed response models rather than raw dicts.
# Constructing the model validates the fixture against the schema at
# build time (missing/mistyped fields fail loudly here instead of
# silently producing a dict that happens to parse), and ``to_jsonable``
# serialises them to the JSON the fake API returns. The strongest,
# non-circular assertions still live in the tests themselves: the
# ``fake_api.last_request`` checks on method / path / params / body.

_NOW_DT = datetime(2025, 1, 1, tzinfo=UTC)


def to_jsonable(obj: Any) -> Any:
    """Recursively turn pydantic models into JSON-ready primitives."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    return obj


def runtime_payload(**over: Any) -> Runtime:
    defaults: dict[str, Any] = {
        "id": RUNTIME_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "Checkout Agent",
        "slug": "checkout-agent",
        "recipe_id": RECIPE_ID,
        "is_active": True,
    }
    defaults.update(over)
    return Runtime(**defaults)


def experiment_payload(**over: Any) -> Experiment:
    defaults: dict[str, Any] = {
        "id": EXPERIMENT_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "prompt-bake-off",
        "status": "running",
    }
    defaults.update(over)
    return Experiment(**defaults)


def recipe_payload(**over: Any) -> Recipe:
    defaults: dict[str, Any] = {
        "id": RECIPE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "repository_id": REPOSITORY_ID,
        "name": "default",
        "slug": "default",
        "git_ref": "main",
        "git_commit_sha": "abc123",
        "created_by_member_id": MEMBER_ID,
        "created_at": _NOW_DT,
        "updated_at": _NOW_DT,
    }
    defaults.update(over)
    return Recipe(**defaults)


def runner_spec_payload(**over: Any) -> RunnerSpec:
    defaults: dict[str, Any] = {
        "session_id": "sess-1",
        "deployment": RunnerDeployment(
            endpoint="https://dp.test",
            slug="dp-us-east",
            region="us-east",
        ),
        "session_token": "runner-jwt",
        "expires_at": _NOW_DT,
        "runtime_context": RunnerContext(
            runtime_id=UUID(RUNTIME_ID), arm_label="control"
        ),
    }
    defaults.update(over)
    return RunnerSpec(**defaults)


def task_payload(**over: Any) -> Task:
    defaults: dict[str, Any] = {
        "id": TASK_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": _NOW_DT,
        "updated_at": _NOW_DT,
        "title": "Summarize repo",
        "status": TaskStatus.PENDING,
    }
    defaults.update(over)
    return Task(**defaults)


def task_run_payload(**over: Any) -> TaskRun:
    defaults: dict[str, Any] = {
        "id": "run-1",
        "task_id": TASK_ID,
        "status": TaskStatus.RUNNING,
    }
    defaults.update(over)
    return TaskRun(**defaults)


def task_create_response() -> TaskCreateResponse:
    return TaskCreateResponse(task=task_payload(), run=task_run_payload())


def task_run_response() -> TaskRunResponse:
    return TaskRunResponse(run=task_run_payload())


def task_cancel_response(run_id: str = "run-1") -> TaskCancelResponse:
    return TaskCancelResponse(id=run_id)


def file_payload(**over: Any) -> File:
    defaults: dict[str, Any] = {
        "id": FILE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": _NOW_DT,
        "updated_at": _NOW_DT,
        "name": "input.jsonl",
        "file_type": FileType.UPLOAD,
        "storage_path": "files/input.jsonl",
        "mime_type": "application/json",
        "size_bytes": 123,
    }
    defaults.update(over)
    return File(**defaults)


def paginated(
    records: list[BaseModel],
    *,
    next: str | None = None,
    total_count: int | None = None,
) -> Paginated[Any]:
    return Paginated[Any](
        records=list(records),
        count=len(records),
        next=next,
        total_count=total_count,
    )
