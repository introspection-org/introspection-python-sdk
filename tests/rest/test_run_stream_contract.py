"""The same pinned SSE/status exchanges run in Swift, JS, Rust and Python."""

import hashlib
import json
import time
from pathlib import Path
from uuid import UUID

import httpx2 as httpx
import pytest

from introspection_sdk import RunFailedError, StreamIncompleteError
from introspection_sdk.runner_resources.tasks import (
    AsyncRunHandle,
    AsyncTaskRuns,
    RunHandle,
    TaskRuns,
)
from introspection_sdk.schemas.tasks import TaskRun, TaskStatus

from .conftest import TASK_ID, FakeAPI

FIXTURE_BYTES = (
    Path(__file__).parents[1] / "fixtures/run-stream-contract.json"
).read_bytes()
SCENARIOS = json.loads(FIXTURE_BYTES)
RUN = TaskRun(id="run-1", task_id=UUID(TASK_ID), status=TaskStatus.RUNNING)
ERRORS = {
    "stream_incomplete": StreamIncompleteError,
    "run_failed": RunFailedError,
}


def test_fixture_hash():
    assert (
        hashlib.sha256(FIXTURE_BYTES).hexdigest()
        == "f1dfd4501a3466442e1201210fc5c7a17150b03787405f22def762aaf511ea78"
    )


def exchanges(fake_api: FakeAPI, scenario: dict) -> list[str]:
    cursors = []
    reads = []

    def stream(request: httpx.Request) -> httpx.Response:
        index = min(len(cursors), len(scenario["streams"]) - 1)
        time.sleep(
            scenario.get("stream_delays_ms", [0] * len(scenario["streams"]))[
                index
            ]
            / 1000
        )
        cursors.append(request.headers.get("last-event-id"))
        return httpx.Response(200, content=scenario["streams"][index].encode())

    def status(request: httpx.Request) -> httpx.Response:
        index = len(reads)
        reads.append(request)
        return httpx.Response(
            200,
            json={
                **RUN.model_dump(mode="json"),
                "status": scenario["statuses"][index],
            },
        )

    path = f"/v1/tasks/{TASK_ID}/runs/run-1"
    fake_api.add_handler("GET", path + "/stream", stream)
    fake_api.add_handler("GET", path, status)
    return cursors


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
def test_shared_contract(fake_api: FakeAPI, scenario: dict):
    cursors = exchanges(fake_api, scenario)
    events = []
    error = None
    try:
        events.extend(
            TaskRuns(fake_api.client()).stream(
                TASK_ID,
                "run-1",
                max_reconnects=2,
                backoff=0.001,
                timeout=scenario.get("timeout_ms", 300000) / 1000,
            )
        )
    except (StreamIncompleteError, RunFailedError) as exc:
        error = exc
    assert [e.delta for e in events if getattr(e, "delta", None)] == scenario[
        "deltas"
    ]
    assert type(error) is (
        ERRORS[scenario["error"]] if "error" in scenario else type(None)
    )
    assert cursors == scenario["cursors"]
    assert len(fake_api.requests) == len(cursors) + len(scenario["statuses"])
    assert not any(
        getattr(e, "result", None) == {"reason": "stream_close"}
        for e in events
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
async def test_shared_contract_async(fake_api: FakeAPI, scenario: dict):
    cursors = exchanges(fake_api, scenario)
    events = []
    error = None
    try:
        async for event in AsyncTaskRuns(fake_api.async_client()).stream(
            TASK_ID,
            "run-1",
            max_reconnects=2,
            backoff=0.001,
            timeout=scenario.get("timeout_ms", 300000) / 1000,
        ):
            events.append(event)
    except (StreamIncompleteError, RunFailedError) as exc:
        error = exc
    assert [e.delta for e in events if getattr(e, "delta", None)] == scenario[
        "deltas"
    ]
    assert type(error) is (
        ERRORS[scenario["error"]] if "error" in scenario else type(None)
    )
    assert cursors == scenario["cursors"]
    assert len(fake_api.requests) == len(cursors) + len(scenario["statuses"])


@pytest.mark.parametrize(
    "scenario",
    [s for s in SCENARIOS if "text_error" in s or s["name"] == "text_chunk"],
    ids=lambda s: s["name"],
)
def test_text_outcome(fake_api: FakeAPI, scenario: dict):
    exchanges(fake_api, scenario)
    handle = RunHandle(None, RUN, TaskRuns(fake_api.client()))
    if "text_error" in scenario:
        with pytest.raises(ERRORS[scenario["text_error"]]):
            handle.text()
    else:
        assert handle.text() == "chunk"


@pytest.mark.parametrize(
    "scenario",
    [s for s in SCENARIOS if "text_error" in s or s["name"] == "text_chunk"],
    ids=lambda s: s["name"],
)
async def test_text_outcome_async(fake_api: FakeAPI, scenario: dict):
    exchanges(fake_api, scenario)
    handle = AsyncRunHandle(None, RUN, AsyncTaskRuns(fake_api.async_client()))
    if "text_error" in scenario:
        with pytest.raises(ERRORS[scenario["text_error"]]):
            await handle.text()
    else:
        assert await handle.text() == "chunk"
