"""Shared fixtures for the REST / Runner surface tests.

These tests drive the REST namespaces through a **real in-process httpx
transport** (:class:`httpx.MockTransport`) backed by a small route table.
Despite the upstream class name, this is not a ``unittest.mock`` object:
the handler runs real Python and returns genuine :class:`httpx.Response`
instances, and nothing in ``introspection_sdk`` is patched or stubbed.
This keeps the suite aligned with ``AGENTS.md`` ("recordings, never
mocks; MagicMock/patch/monkeypatch reserved for pure-unit helpers")
while running fully offline — there is no live Introspection backend to
record cassettes against in CI.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from introspection_sdk._http import _HttpClient

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

_NOW = "2025-01-01T00:00:00Z"


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
                kwargs["json"] = json_body
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


def runtime_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": RUNTIME_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "checkout-agent",
        "recipe_id": RECIPE_ID,
        "is_active": True,
    }
    base.update(over)
    return base


def experiment_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": EXPERIMENT_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "prompt-bake-off",
        "status": "running",
    }
    base.update(over)
    return base


def recipe_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": RECIPE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "repository_id": REPOSITORY_ID,
        "name": "default",
        "slug": "default",
        "git_ref": "main",
        "git_commit_sha": "abc123",
        "created_by_member_id": MEMBER_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(over)
    return base


def runner_spec_payload(**over: Any) -> dict[str, Any]:
    base = {
        "session_id": "sess-1",
        "deployment": {
            "endpoint": "https://dp.test",
            "slug": "dp-us-east",
            "region": "us-east",
        },
        "session_token": "runner-jwt",
        "expires_at": _NOW,
        "runtime_context": {
            "runtime_id": RUNTIME_ID,
            "arm_label": "control",
        },
    }
    base.update(over)
    return base


def task_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": TASK_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
        "title": "Summarize repo",
        "status": "pending",
    }
    base.update(over)
    return base


def task_run_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": "run-1",
        "task_id": TASK_ID,
        "status": "running",
    }
    base.update(over)
    return base


def file_payload(**over: Any) -> dict[str, Any]:
    base = {
        "id": FILE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
        "name": "input.jsonl",
        "file_type": "upload",
        "storage_path": "files/input.jsonl",
        "mime_type": "application/json",
        "size_bytes": 123,
    }
    base.update(over)
    return base


def paginated(
    records: list[dict[str, Any]],
    *,
    next: str | None = None,
    total_count: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"records": records, "count": len(records)}
    if next is not None:
        out["next"] = next
    if total_count is not None:
        out["total_count"] = total_count
    return out
