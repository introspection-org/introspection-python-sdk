"""The client and the Runner expose one data-plane interface.

``DataPlaneResources`` / ``AsyncDataPlaneResources`` are the contract. The
module-level assignments below are checked by the type checker in CI
(``ty check``), so a namespace or method that drifts between the client and
the Runner fails the build; the ``isinstance`` tests check the same at run
time. ``_drive`` / ``_adrive`` are written against the Protocol alone and run
against both handles over a real loopback DP origin, asserting each one sends
its own credential.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from introspection_sdk import AsyncIntrospectionClient, IntrospectionClient
from introspection_sdk.protocols import (
    AsyncDataPlaneResources,
    DataPlaneResources,
)
from introspection_sdk.runner import AsyncRunner, Runner
from introspection_sdk.schemas.runner import RunnerDeployment, RunnerSpec

from .conftest import (
    ISSUE_ID,
    TASK_ID,
    LocalDP,
    file_payload,
    issue_payload,
    paginated,
    runner_spec_payload,
    task_payload,
    task_run_payload,
)


def _typed_client(client: IntrospectionClient) -> DataPlaneResources:
    return client


def _typed_runner(runner: Runner) -> DataPlaneResources:
    return runner


def _typed_async_client(
    client: AsyncIntrospectionClient,
) -> AsyncDataPlaneResources:
    return client


def _typed_async_runner(runner: AsyncRunner) -> AsyncDataPlaneResources:
    return runner


AUTOMATION = {
    "id": "0199a1b2-0000-7000-8000-000000000001",
    "org_id": "00000000-0000-0000-0000-0000000000aa",
    "project_id": "00000000-0000-0000-0000-0000000000bb",
    "name": "Weekly digest",
    "enabled": True,
    "trigger_type": "cron",
    "created_at": "2026-09-01T10:00:00Z",
    "updated_at": "2026-09-01T10:00:00Z",
}
METRIC_RESPONSE: dict[str, Any] = {
    "rows": [],
    "meta": {
        "view": "conversations",
        "window": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        "row_count": 0,
        "row_limit": 100,
    },
}
METRIC_QUERY: dict[str, Any] = {
    "view": "conversations",
    "metrics": [{"aggregation": "count"}],
    "from_timestamp": "2025-01-01T00:00:00Z",
    "to_timestamp": "2025-01-02T00:00:00Z",
}
EXPECTED_PATHS = [
    ("GET", f"/v1/tasks/{TASK_ID}"),
    ("GET", f"/v1/tasks/{TASK_ID}/runs/run-1"),
    ("GET", "/v1/files"),
    ("GET", "/v1/conversations"),
    ("GET", "/v1/events"),
    ("POST", "/v1/metrics"),
    ("GET", "/v1/shares"),
    ("GET", "/v1/automations"),
    ("GET", "/v1/issues"),
    ("GET", f"/v1/issues/{ISSUE_ID}"),
]


def _seed(dp: LocalDP) -> None:
    dp.add("GET", f"/v1/tasks/{TASK_ID}", task_payload())
    dp.add("GET", f"/v1/tasks/{TASK_ID}/runs/run-1", task_run_payload())
    dp.add("GET", "/v1/files", paginated([file_payload()]))
    dp.add("GET", "/v1/conversations", paginated([]))
    dp.add("GET", "/v1/events", paginated([]))
    dp.add("POST", "/v1/metrics", METRIC_RESPONSE)
    dp.add("GET", "/v1/shares", paginated([]))
    dp.add(
        "GET",
        "/v1/automations",
        {"records": [AUTOMATION], "count": 1, "next": None},
    )
    dp.add("GET", "/v1/issues", paginated([issue_payload()]))
    dp.add("GET", f"/v1/issues/{ISSUE_ID}", issue_payload())


def _spec(dp: LocalDP) -> RunnerSpec:
    return runner_spec_payload(
        session_token="runner-jwt",
        deployment=RunnerDeployment(
            endpoint=dp.endpoint, slug="dp", region="us-east"
        ),
    )


def _drive(dp: DataPlaneResources) -> None:
    assert str(dp.tasks.get(TASK_ID).id) == TASK_ID
    assert dp.tasks.runs.get(TASK_ID, "run-1").id == "run-1"
    assert dp.files.list().page().count == 1
    assert dp.conversations.list().page().count == 0
    assert dp.events.list("identify").page().count == 0
    assert dp.metrics.query(METRIC_QUERY).meta.row_count == 0
    assert dp.shares.list().page().count == 0
    assert dp.automations.list().page().count == 1
    assert dp.issues.list().page().count == 1
    assert dp.issues.get(ISSUE_ID).revision == 3


async def _adrive(dp: AsyncDataPlaneResources) -> None:
    assert str((await dp.tasks.get(TASK_ID)).id) == TASK_ID
    assert (await dp.tasks.runs.get(TASK_ID, "run-1")).id == "run-1"
    assert (await dp.files.list().page()).count == 1
    assert (await dp.conversations.list().page()).count == 0
    assert (await dp.events.list("identify").page()).count == 0
    assert (await dp.metrics.query(METRIC_QUERY)).meta.row_count == 0
    assert (await dp.shares.list().page()).count == 0
    assert (await dp.automations.list().page()).count == 1
    assert (await dp.issues.list().page()).count == 1
    assert (await dp.issues.get(ISSUE_ID)).revision == 3


def _calls(dp: LocalDP) -> list[tuple[str, str]]:
    return [(r.method, r.path) for r in dp.requests]


def test_client_and_runner_satisfy_the_protocol_at_run_time(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    client = IntrospectionClient(token="t", dp_url=dp.endpoint)
    spec = _spec(dp)
    runner = Runner(spec, refresher=lambda: spec)
    try:
        assert isinstance(client, DataPlaneResources)
        assert isinstance(runner, DataPlaneResources)
        assert isinstance(_typed_client(client), DataPlaneResources)
        assert isinstance(_typed_runner(runner), DataPlaneResources)
    finally:
        client.shutdown()
        runner.close()


async def test_async_client_and_runner_satisfy_the_protocol_at_run_time(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    spec = _spec(dp)

    async def refresher() -> RunnerSpec:
        return spec

    async with (
        AsyncIntrospectionClient(token="t", dp_url=dp.endpoint) as client,
        AsyncRunner(spec, refresher=refresher) as runner,
    ):
        assert isinstance(_typed_async_client(client), AsyncDataPlaneResources)
        assert isinstance(_typed_async_runner(runner), AsyncDataPlaneResources)


def test_every_namespace_works_through_the_client(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    client = IntrospectionClient(
        token="client-token",
        base_api_url="https://api.test",
        dp_url=dp.endpoint,
    )
    try:
        _drive(client)
    finally:
        client.shutdown()

    assert _calls(dp) == EXPECTED_PATHS
    assert {r.authorization for r in dp.requests} == {"Bearer client-token"}


def test_every_namespace_works_through_the_runner(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    spec = _spec(dp)
    with Runner(spec, refresher=lambda: spec) as runner:
        _drive(runner)

    assert _calls(dp) == EXPECTED_PATHS
    assert {r.authorization for r in dp.requests} == {"Bearer runner-jwt"}


async def test_every_namespace_works_through_the_async_client(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    async with AsyncIntrospectionClient(
        token="client-token",
        base_api_url="https://api.test",
        dp_url=dp.endpoint,
    ) as client:
        await _adrive(client)

    assert _calls(dp) == EXPECTED_PATHS
    assert {r.authorization for r in dp.requests} == {"Bearer client-token"}


async def test_every_namespace_works_through_the_async_runner(
    local_dp: Callable[[], LocalDP],
):
    dp = local_dp()
    _seed(dp)
    spec = _spec(dp)

    async def refresher() -> RunnerSpec:
        return spec

    async with AsyncRunner(spec, refresher=refresher) as runner:
        await _adrive(runner)

    assert _calls(dp) == EXPECTED_PATHS
    assert {r.authorization for r in dp.requests} == {"Bearer runner-jwt"}
