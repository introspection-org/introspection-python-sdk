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
not a recording of a live exchange, so these tests do **not** verify
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
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.schemas.connectors import (
    Connection,
    Connector,
    ConnectorAuthorization,
)
from introspection_sdk.schemas.experiments import Experiment
from introspection_sdk.schemas.files import File, FileType
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.recipes import Recipe
from introspection_sdk.schemas.runner import (
    RunnerContext,
    RunnerDeployment,
    RunnerRecipeSummary,
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
CONNECTOR_ID = "77777777-7777-7777-7777-777777777777"
CONNECTION_ID = "88888888-8888-8888-8888-888888888888"
RUNTIME_GROUP_ID = "99999999-9999-9999-9999-999999999999"
INSTALLER_MEMBER_ID = "00000000-0000-0000-0000-0000000000dd"


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


# --- Real loopback server standing in for a DP deployment -----------
#
# ``MockTransport`` cannot serve the Runner: the Runner builds its own
# ``httpx.Client`` from ``spec.deployment.endpoint`` and there is no
# transport seam to inject (deliberately — the endpoint the Runner talks
# to must come from the spec, not from the caller). To prove the Runner
# really points its traffic at the endpoint the CP handed back, and
# re-points it after ``refresh()``, the DP side has to be a real origin
# with a real port. These fixtures start one per deployment on
# 127.0.0.1, so the endpoint in the spec is the thing under test rather
# than an assertion about a mock.


@dataclass
class LocalRequest:
    """A request a :class:`LocalDP` server actually received."""

    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: bytes

    @property
    def authorization(self) -> str | None:
        return self.headers.get("authorization")


class LocalDP:
    """A real HTTP origin on 127.0.0.1 standing in for a DP deployment."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, Any]] = {}
        self.requests: list[LocalRequest] = []
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0), self._handler_class()
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def add(
        self, method: str, path: str, body: Any, status: int = 200
    ) -> None:
        self.routes[(method.upper(), path)] = (status, body)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        dp = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                """Keep the test output clean."""

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                parsed = urlsplit(self.path)
                dp.requests.append(
                    LocalRequest(
                        method=self.command or "",
                        path=parsed.path,
                        query=parsed.query,
                        headers={
                            k.lower(): v for k, v in self.headers.items()
                        },
                        body=body,
                    )
                )
                route = dp.routes.get(
                    ((self.command or "").upper(), parsed.path)
                )
                if route is None:
                    status, payload = (
                        404,
                        {
                            "detail": f"no route for {self.command} {parsed.path}"
                        },
                    )
                else:
                    status, payload = route
                encoded = _json.dumps(to_jsonable(payload)).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            do_GET = _serve
            do_POST = _serve
            do_PATCH = _serve
            do_DELETE = _serve

        return Handler


@pytest.fixture
def local_dp() -> Iterator[Callable[[], LocalDP]]:
    """Factory starting loopback DP origins, torn down after the test."""
    started: list[LocalDP] = []

    def make() -> LocalDP:
        dp = LocalDP()
        started.append(dp)
        return dp

    yield make
    for dp in started:
        dp.close()


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


def connector_payload(**over: Any) -> Connector:
    defaults: dict[str, Any] = {
        "id": CONNECTOR_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": _NOW_DT,
        "updated_at": _NOW_DT,
        "slug": "slack-support",
        "name": "Slack (support)",
        "provider": "slack",
        "auth_mode": "oauth_stored",
        "environment": "production",
        "scopes": ["chat:write"],
        "api_hosts": ["slack.com"],
        "status": "active",
        # Slack delivers conversations, so authorize must name a runtime.
        "requires_runtime": True,
    }
    defaults.update(over)
    return Connector(**defaults)


def connection_payload(**over: Any) -> Connection:
    defaults: dict[str, Any] = {
        "id": CONNECTION_ID,
        "org_id": ORG_ID,
        "created_at": _NOW_DT,
        "updated_at": _NOW_DT,
        "connector_id": CONNECTOR_ID,
        "member_id": MEMBER_ID,
        "created_by_member_id": INSTALLER_MEMBER_ID,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "subject_type": "workspace",
        "scopes_granted": ["chat:write"],
        "status": "active",
    }
    defaults.update(over)
    return Connection(**defaults)


def connector_authorization_payload(**over: Any) -> ConnectorAuthorization:
    defaults: dict[str, Any] = {
        "authorize_url": (
            "https://slack.com/oauth/v2/authorize"
            "?client_id=abc&state=single-use-token"
        ),
        "expires_in": 3600,
        "expires_at": datetime(2025, 1, 1, 1, tzinfo=UTC),
    }
    defaults.update(over)
    return ConnectorAuthorization(**defaults)


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
            runtime_id=UUID(RUNTIME_ID),
            runtime_group_id=UUID("88888888-8888-8888-8888-888888888888"),
            recipe_id=UUID(RECIPE_ID),
            recipe_repository_id=UUID(REPOSITORY_ID),
            recipe_git_ref="main",
            recipe_git_commit_sha="abc123",
            recipe=RunnerRecipeSummary(
                repository_id=UUID(REPOSITORY_ID),
                git_ref="main",
                git_commit_sha="abc123",
            ),
            arm_label="control",
            agent_name="agent",
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
        "identity_key": "user:u-1",
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
