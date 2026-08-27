"""End-to-end lifecycle of a :class:`~introspection_sdk.runner.Runner`.

``test_runner.py`` covers the Runner in isolation, with a stub refresher
and no traffic. This module drives the whole loop instead: the CP
``/run`` route mints a spec, the Runner's namespaces issue real requests
to the DP origin named in that spec, ``refresh()`` re-mints and
re-points them at a *different* origin with a *different* token, and
``close()`` shuts the door — including on a namespace handle taken
before the close.

The CP side is the offline :class:`FakeAPI` transport; the DP side is a
real loopback HTTP server per deployment (see ``conftest.LocalDP``),
because "the Runner talks to the endpoint the spec named" is only
provable when the endpoint is a real address the Runner had to resolve
itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2 as httpx
import pytest

from introspection_sdk._errors import RunnerExpiredError
from introspection_sdk.resources.runtimes import AsyncRuntimes, Runtimes
from introspection_sdk.runner_resources import (
    AsyncConversations,
    AsyncEvents,
    AsyncFiles,
    AsyncMetrics,
    AsyncShares,
    AsyncTasks,
    Conversations,
    Events,
    Files,
    Metrics,
    Shares,
    Tasks,
)
from introspection_sdk.schemas.runner import RunnerDeployment

from .conftest import (
    RECIPE_ID,
    RUNTIME_ID,
    TASK_ID,
    FakeAPI,
    LocalDP,
    file_payload,
    paginated,
    runner_spec_payload,
    runtime_payload,
    task_payload,
    to_jsonable,
)

METRIC_RESPONSE: dict[str, Any] = {
    "data": [],
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


def _seed_dp(dp: LocalDP) -> None:
    """Give a DP origin one route per namespace the Runner exposes."""
    dp.add("GET", f"/v1/tasks/{TASK_ID}", task_payload())
    dp.add("GET", "/v1/files", paginated([file_payload()]))
    dp.add("GET", "/v1/conversations", paginated([]))
    dp.add("GET", "/v1/events", paginated([]))
    dp.add("GET", "/v1/shares", paginated([]))
    dp.add("POST", "/v1/metrics", METRIC_RESPONSE)


def _seed_cp(fake_api: FakeAPI, dp_a: LocalDP, dp_b: LocalDP) -> list[bytes]:
    """Wire the CP resolve + ``/run`` routes.

    The first ``/run`` hands back ``dp_a``; every later one (i.e.
    ``refresh()``) hands back ``dp_b`` with a different session token, so
    a Runner that failed to re-point would keep hitting ``dp_a``.
    """
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    specs = [
        runner_spec_payload(
            session_id="sess-a",
            session_token="jwt-a",
            deployment=RunnerDeployment(
                endpoint=dp_a.endpoint, slug="dp-a", region="us-east"
            ),
        ),
        runner_spec_payload(
            session_id="sess-b",
            session_token="jwt-b",
            deployment=RunnerDeployment(
                endpoint=dp_b.endpoint, slug="dp-b", region="eu-west"
            ),
        ),
    ]
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        spec = specs[min(len(bodies), len(specs) - 1)]
        bodies.append(request.read())
        return httpx.Response(200, json=to_jsonable(spec))

    fake_api.add_handler("POST", f"/v1/runtimes/{RUNTIME_ID}/run", handler)
    return bodies


def _dp_calls(dp: LocalDP) -> list[tuple[str, str, str | None]]:
    return [(r.method, r.path, r.authorization) for r in dp.requests]


def test_open_read_refresh_close_sync(
    fake_api: FakeAPI, local_dp: Callable[[], LocalDP]
):
    dp_a, dp_b = local_dp(), local_dp()
    _seed_dp(dp_a)
    _seed_dp(dp_b)
    run_bodies = _seed_cp(fake_api, dp_a, dp_b)

    runner = Runtimes(fake_api.client())("checkout-agent").run(
        agent_name="agent"
    )

    # The CP `/run` call happened, and its answer is what the accessors
    # report.
    assert [r.path for r in fake_api.requests] == [
        "/v1/runtimes",
        f"/v1/runtimes/{RUNTIME_ID}/run",
    ]
    assert run_bodies == [b'{"agent_name":"agent","ttl_seconds":3600}']
    assert runner.session_id == "sess-a"
    assert runner.dp_endpoint == dp_a.endpoint
    assert runner.deployment.slug == "dp-a"
    assert runner.deployment.region == "us-east"
    assert str(runner.context.runtime_id) == RUNTIME_ID
    assert str(runner.context.recipe_id) == RECIPE_ID
    assert runner.expires_at == runner.spec.expires_at

    # Every namespace issues its request against the endpoint the spec
    # named, bearing the spec's session token.
    assert isinstance(runner.tasks, Tasks)
    assert isinstance(runner.files, Files)
    assert isinstance(runner.conversations, Conversations)
    assert isinstance(runner.events, Events)
    assert isinstance(runner.metrics, Metrics)
    assert isinstance(runner.shares, Shares)

    assert str(runner.tasks.get(TASK_ID).id) == TASK_ID
    assert runner.files.list().page().count == 1
    assert runner.conversations.list().page().count == 0
    assert runner.events.list("identify").page().count == 0
    assert runner.shares.list().page().count == 0
    assert runner.metrics.query(METRIC_QUERY).meta.row_count == 0

    assert _dp_calls(dp_a) == [
        ("GET", f"/v1/tasks/{TASK_ID}", "Bearer jwt-a"),
        ("GET", "/v1/files", "Bearer jwt-a"),
        ("GET", "/v1/conversations", "Bearer jwt-a"),
        ("GET", "/v1/events", "Bearer jwt-a"),
        ("GET", "/v1/shares", "Bearer jwt-a"),
        ("POST", "/v1/metrics", "Bearer jwt-a"),
    ]
    assert dp_b.requests == []

    # `refresh()` re-mints via CP and re-points the namespaces at the new
    # deployment with the new token.
    stale = runner.tasks
    runner.refresh()
    assert len(run_bodies) == 2
    assert runner.session_id == "sess-b"
    assert runner.dp_endpoint == dp_b.endpoint
    assert runner.deployment.region == "eu-west"

    before = len(dp_a.requests)
    assert str(runner.tasks.get(TASK_ID).id) == TASK_ID
    assert _dp_calls(dp_b) == [("GET", f"/v1/tasks/{TASK_ID}", "Bearer jwt-b")]
    assert len(dp_a.requests) == before

    # A handle captured before the refresh points at the retired client
    # and must refuse in the SDK's own error type, not httpx's.
    with pytest.raises(RunnerExpiredError):
        stale.get(TASK_ID)

    live = runner.tasks
    runner.close()
    with pytest.raises(RunnerExpiredError):
        live.get(TASK_ID)
    with pytest.raises(RunnerExpiredError):
        _ = runner.tasks
    with pytest.raises(RunnerExpiredError):
        runner.refresh()
    # Nothing reached either origin after the close.
    assert len(dp_b.requests) == 1
    assert len(run_bodies) == 2


async def test_open_read_refresh_close_async(
    fake_api: FakeAPI, local_dp: Callable[[], LocalDP]
):
    dp_a, dp_b = local_dp(), local_dp()
    _seed_dp(dp_a)
    _seed_dp(dp_b)
    run_bodies = _seed_cp(fake_api, dp_a, dp_b)

    runner = await AsyncRuntimes(fake_api.async_client())(
        "checkout-agent"
    ).run(agent_name="agent")

    assert [r.path for r in fake_api.requests] == [
        "/v1/runtimes",
        f"/v1/runtimes/{RUNTIME_ID}/run",
    ]
    assert runner.session_id == "sess-a"
    assert runner.dp_endpoint == dp_a.endpoint
    assert runner.deployment.slug == "dp-a"
    assert str(runner.context.runtime_id) == RUNTIME_ID
    assert runner.expires_at == runner.spec.expires_at

    assert isinstance(runner.tasks, AsyncTasks)
    assert isinstance(runner.files, AsyncFiles)
    assert isinstance(runner.conversations, AsyncConversations)
    assert isinstance(runner.events, AsyncEvents)
    assert isinstance(runner.metrics, AsyncMetrics)
    assert isinstance(runner.shares, AsyncShares)

    assert str((await runner.tasks.get(TASK_ID)).id) == TASK_ID
    assert (await runner.files.list().page()).count == 1
    assert (await runner.conversations.list().page()).count == 0
    assert (await runner.events.list("identify").page()).count == 0
    assert (await runner.shares.list().page()).count == 0
    assert (await runner.metrics.query(METRIC_QUERY)).meta.row_count == 0

    assert _dp_calls(dp_a) == [
        ("GET", f"/v1/tasks/{TASK_ID}", "Bearer jwt-a"),
        ("GET", "/v1/files", "Bearer jwt-a"),
        ("GET", "/v1/conversations", "Bearer jwt-a"),
        ("GET", "/v1/events", "Bearer jwt-a"),
        ("GET", "/v1/shares", "Bearer jwt-a"),
        ("POST", "/v1/metrics", "Bearer jwt-a"),
    ]
    assert dp_b.requests == []

    stale = runner.tasks
    await runner.refresh()
    assert len(run_bodies) == 2
    assert runner.session_id == "sess-b"
    assert runner.dp_endpoint == dp_b.endpoint

    before = len(dp_a.requests)
    assert str((await runner.tasks.get(TASK_ID)).id) == TASK_ID
    assert _dp_calls(dp_b) == [("GET", f"/v1/tasks/{TASK_ID}", "Bearer jwt-b")]
    assert len(dp_a.requests) == before

    with pytest.raises(RunnerExpiredError):
        await stale.get(TASK_ID)

    live = runner.tasks
    await runner.close()
    with pytest.raises(RunnerExpiredError):
        await live.get(TASK_ID)
    with pytest.raises(RunnerExpiredError):
        _ = runner.tasks
    with pytest.raises(RunnerExpiredError):
        await runner.refresh()
    assert len(dp_b.requests) == 1
    assert len(run_bodies) == 2
