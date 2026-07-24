"""Tests for :class:`introspection_sdk.runner.Runner`.

The Runner owns its own HTTP client; these tests exercise its lifecycle and
accessors without issuing requests.
"""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk._errors import IntrospectionAPIError
from introspection_sdk.runner import Runner
from introspection_sdk.runner_resources import Files, Tasks
from introspection_sdk.schemas.runner import RunnerSpec

from .conftest import RUNTIME_ID, runner_spec_payload


def _spec(**over: Any) -> RunnerSpec:
    return runner_spec_payload(**over)


def _runner() -> Runner:
    return Runner(_spec())


def test_accessors_reflect_spec():
    runner = _runner()
    assert runner.session_id == "sess-1"
    assert runner.dp_endpoint == "https://dp.test"
    assert runner.deployment.region == "us-east"
    assert str(runner.context.runtime_id) == RUNTIME_ID
    assert runner.spec.session_token == "runner-jwt"
    assert runner.expires_at is not None


def test_tasks_and_files_namespaces():
    runner = _runner()
    assert isinstance(runner.tasks, Tasks)
    assert isinstance(runner.files, Files)
    assert runner.tasks is runner.tasks
    assert runner.files is runner.files
    assert runner.conversations is runner.conversations
    assert runner.events is runner.events
    assert runner.metrics is runner.metrics
    assert runner.shares is runner.shares


def test_close_blocks_further_use():
    runner = _runner()
    runner.close()
    with pytest.raises(IntrospectionAPIError, match="has been closed"):
        _ = runner.tasks
    with pytest.raises(IntrospectionAPIError):
        _ = runner.files


def test_context_manager_closes_on_exit():
    spec = _spec()
    with Runner(spec) as runner:
        assert runner.session_id == "sess-1"
    with pytest.raises(IntrospectionAPIError):
        _ = runner.tasks


def test_additional_headers_are_copied():
    spec = _spec()
    headers = {"x-trace": "1"}
    runner = Runner(spec, additional_headers=headers)
    headers["x-trace"] = "mutated"
    # Runner copied the mapping; the later mutation must not leak in.
    assert runner._additional_headers == {"x-trace": "1"}
